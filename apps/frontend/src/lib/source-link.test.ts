import { describe, expect, it } from 'vitest'
import { sourceHref } from './source-link'

describe('sourceHref', () => {
   it('prefers the trusted backend deep link', () => {
      expect(
         sourceHref({
            id: 'unit',
            title: 'Điều 1',
            content: '',
            deep_link: '/explorer?document=doc&article=art1',
         }),
      ).toBe('/explorer?document=doc&article=art1')
   })

   it('builds a deterministic fallback from canonical parent IDs', () => {
      expect(
         sourceHref({
            id: 'clause',
            title: 'Khoản 2',
            content: '',
            document_id: 'ldn_2020',
            article_id: 'ldn_2020_art17',
            clause_id: 'ldn_2020_art17_cl2',
         }),
      ).toBe('/explorer?document=ldn_2020&article=ldn_2020_art17&clause=ldn_2020_art17_cl2')
   })

   it('maps an unsupported backend unit route through explorer parents', () => {
      expect(
         sourceHref({
            id: 'clause',
            title: 'Khoản 2',
            content: '',
            deep_link: '/documents/ldn_2020/units/ldn_2020_art17_cl2',
            document_id: 'ldn_2020',
            article_id: 'ldn_2020_art17',
            clause_id: 'ldn_2020_art17_cl2',
         }),
      ).toBe('/explorer?document=ldn_2020&article=ldn_2020_art17&clause=ldn_2020_art17_cl2')
   })

   it('returns null when no navigation identity is available', () => {
      expect(sourceHref({ id: 'legacy', title: 'Legacy', content: '' })).toBeNull()
   })
})
