import { Extension } from '@tiptap/core'

const PRESERVED_ATTRIBUTES = [
  'style',
  'class',
  'width',
  'height',
  'align',
  'valign',
  'bgcolor',
  'border',
  'cellpadding',
  'cellspacing',
  'colspan',
  'rowspan',
  'data-var',
]

const ATTRIBUTE_NODE_TYPES = [
  'paragraph',
  'heading',
  'bulletList',
  'orderedList',
  'listItem',
  'blockquote',
  'codeBlock',
  'horizontalRule',
  'table',
  'tableRow',
  'tableCell',
  'tableHeader',
  'emailImage',
]

export const PreserveEmailAttributes = Extension.create({
  name: 'preserveEmailAttributes',

  addGlobalAttributes() {
    return [
      {
        types: ATTRIBUTE_NODE_TYPES,
        attributes: Object.fromEntries(
          PRESERVED_ATTRIBUTES.map((name) => [
            name,
            {
              default: null,
              parseHTML: (element) => element.getAttribute(name),
              renderHTML: (attributes) => {
                const value = attributes[name]
                return value == null || value === '' ? {} : { [name]: value }
              },
            },
          ])
        ),
      },
    ]
  },
})
