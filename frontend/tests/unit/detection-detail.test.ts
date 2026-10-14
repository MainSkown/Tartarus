import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import type { Detection } from '@/api'
import DetectionDetail from '@/components/DetectionDetail.vue'
import { MAX_QUERY_LENGTH } from '@/services/event-id-query'
import { detectionFixture, relatedEvent } from './detections-fixtures'
import { filterEventsPlugins } from './filter-events-plugins'

const { plugins, router, query } = await filterEventsPlugins('/analyses/45/detections?q=old&f=api%3AWriteFile&pid=12')

function mountDetail(overrides: Partial<Detection> = {}) {
  return mount(DetectionDetail, { global: { plugins }, props: { detection: detectionFixture(overrides) } })
}

const withEvents = (count: number, total = count): Partial<Detection> => ({
  related_events: Array.from({ length: count }, (_, i) => relatedEvent(i)),
  related_event_total: total,
})

beforeEach(async () => {
  query.reset()
  query.restore({ text: 'old', chips: [{ field: 'api', value: 'WriteFile', negate: false }], pids: [12], timeRange: null, eventId: null })
  await router.push('/analyses/45/detections')
})

describe('DetectionDetail filter on rule', () => {
  it('has a button that filters the events on the rule name', async () => {
    const wrapper = mountDetail({ name: 'recon_systeminfo' })
    const button = wrapper.get('.detection-detail__rule-filter')
    expect(button.attributes('aria-label')).toBe('Show events with rule.name: recon_systeminfo')
    await button.trigger('click')
    await flushPromises()
    expect(query.chips).toEqual([
      { field: 'api', value: 'WriteFile', negate: false },
      { field: 'rule.name', value: 'recon_systeminfo', negate: false },
    ])
    expect(router.currentRoute.value.params.tab).toBe('events')
  })
})

describe('DetectionDetail show these events', () => {
  it('has no such button when the detection has no triggering events', () => {
    expect(mountDetail().find('.detection-detail__show-events').exists()).toBe(false)
  })

  it('replaces the query with one over the triggering event ids and opens Events, clearing nothing else', async () => {
    const wrapper = mountDetail(withEvents(3))
    const button = wrapper.get('.detection-detail__show-events')
    expect(button.text()).toBe('[SHOW THESE EVENTS]')
    await button.trigger('click')
    await flushPromises()
    expect(query.text).toBe('event.id:(event-0 OR event-1 OR event-2)')
    expect(query.chips).toHaveLength(1)
    expect(query.pids).toEqual([12])
    expect(router.currentRoute.value.params.tab).toBe('events')
  })

  it('says nothing about a cut when the query names every event', () => {
    expect(mountDetail(withEvents(3)).find('.detection-detail__events-cut').exists()).toBe(false)
  })

  it('leaves the "shown of total" text to the events count when the API listed fewer events than there are', () => {
    const wrapper = mountDetail(withEvents(3, 40))
    expect(wrapper.find('.detection-detail__events-cut').exists()).toBe(false)
    expect(wrapper.get('.detection-detail__events-count').text()).toBe('3 of 40 shown')
  })

  it('names at most 50 events', async () => {
    const wrapper = mountDetail(withEvents(80))
    await wrapper.get('.detection-detail__show-events').trigger('click')
    await flushPromises()
    expect(query.text.split(' OR ')).toHaveLength(50)
    expect(wrapper.get('.detection-detail__events-cut').text()).toBe('the query names 50 of 80')
  })

  it('names fewer events when all of them would not fit the query length limit', async () => {
    const long = Array.from({ length: 50 }, (_, i) => ({ ...relatedEvent(i), id: `${i}-${'x'.repeat(78)}` }))
    const wrapper = mountDetail({ related_events: long, related_event_total: 50 })
    await wrapper.get('.detection-detail__show-events').trigger('click')
    await flushPromises()
    expect(query.text.length).toBeLessThanOrEqual(MAX_QUERY_LENGTH)
    expect(wrapper.get('.detection-detail__events-cut').text()).toMatch(/^the query names \d+ of 50$/)
  })
})
