import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/http'
import { rejectReason, toEntries, uploadSequentially, uploadSummary } from './uploadQueue'

const file = (name: string, size = 10) => new File([new Uint8Array(size)], name)

describe('rejectReason', () => {
  it('rejects oversize and unsupported files client-side with a Dutch reason', () => {
    expect(rejectReason(file('manual.pdf'))).toBeNull()
    expect(rejectReason(file('data.JSON'))).toBeNull()
    expect(rejectReason(file('archive.zip'))).toMatch(/niet ondersteund/)
    const big = { name: 'big.csv', size: 64 * 1024 * 1024 + 1 } as File
    expect(rejectReason(big)).toMatch(/64 MiB/)
  })
})

describe('uploadSequentially', () => {
  it('uploads one at a time, keeps going after a failure and reports every step', async () => {
    const order: string[] = []
    let inFlight = 0
    let maxInFlight = 0
    const upload = async (f: File) => {
      inFlight += 1
      maxInFlight = Math.max(maxInFlight, inFlight)
      order.push(f.name)
      await Promise.resolve()
      inFlight -= 1
      if (f.name === 'bad.csv') throw new ApiError(422, 'Kolomkoppen ontbreken in rij 1.')
      return { id: f.name }
    }
    const reports: string[][] = []
    const entries = toEntries([file('a.pdf'), file('bad.csv'), file('skip.exe'), file('c.txt')])
    const result = await uploadSequentially(entries, upload, (list) => reports.push(list.map((e) => e.state)))

    expect(order).toEqual(['a.pdf', 'bad.csv', 'c.txt'])
    expect(maxInFlight).toBe(1)
    expect(result.map((e) => e.state)).toEqual(['klaar', 'fout', 'overgeslagen', 'klaar'])
    expect(result[1]?.error).toBe('Kolomkoppen ontbreken in rij 1.')
    expect(reports[0]).toEqual(['bezig', 'wachtend', 'overgeslagen', 'wachtend'])
    expect(uploadSummary(result)).toEqual({ done: 2, failed: 1, skipped: 1, busy: false })
  })
})
