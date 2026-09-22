import { splitCitations } from './citations'

/**
 * remark plugin: turns `[E1]` / `[E1, E2]` inside Markdown text into citation
 * nodes that render as `<span data-citation="E1">`. AnswerMarkdown maps that
 * span to a button (or to a visibly invalid marker).
 *
 * Only a structural subset of mdast is typed here so the app does not import
 * transitive packages it does not declare.
 */
interface MdNode {
  type: string
  value?: string
  identifier?: string
  label?: string
  children?: MdNode[]
  data?: { hName: string; hProperties: Record<string, string> }
}

const CITATION_ID = /^e\d{1,4}$/i

function citationNode(marker: string): MdNode {
  return {
    type: 'citation',
    data: { hName: 'span', hProperties: { dataCitation: marker } },
    children: [{ type: 'text', value: marker }],
  }
}

function transform(node: MdNode): MdNode[] {
  // A model-written `[E1]: https://…` definition would turn every [E1] into an
  // ordinary link. Citations must only ever open evidence, so drop it and
  // treat the reference as the plain marker it was meant to be.
  if (node.type === 'definition' && CITATION_ID.test(node.identifier ?? '')) return []
  if (node.type === 'linkReference' && CITATION_ID.test(node.identifier ?? '')) {
    return [citationNode((node.label ?? node.identifier ?? '').toUpperCase())]
  }
  if (node.type === 'text' && node.value) {
    return splitCitations(node.value).flatMap((segment): MdNode[] => {
      if (segment.type === 'text') return [{ type: 'text', value: segment.text }]
      // A group renders as adjacent markers; separators are not needed.
      return segment.markers.map(citationNode)
    })
  }
  // Code is literal: never rewrite inside `inlineCode` or `code` (no children).
  if (node.children) node.children = node.children.flatMap(transform)
  return [node]
}

export function remarkCitations() {
  return (tree: MdNode): void => {
    transform(tree)
  }
}
