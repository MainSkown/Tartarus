import { describe, expect, it } from 'vitest'
import { detectionById, displayedGroups, rulesetLabel } from '@/services/detection-groups'
import {
  CAPE_DLL_ID,
  CAPE_RECON_ID,
  DETECTIONS_VIEW,
  SIGMA_ID,
  SURICATA_ID,
  detectionFixture,
} from './detections-fixtures'

describe('displayedGroups', () => {
  it('orders the rulesets sigma, cape, yara, suricata and drops none that exist', () => {
    expect(displayedGroups(DETECTIONS_VIEW.groups).map((group) => group.ruleset)).toEqual(['sigma', 'cape', 'suricata'])
  })

  it('puts a ruleset it does not know after the known ones', () => {
    const groups = [
      { ruleset: 'custom', detections: [detectionFixture({ id: 'a' })] },
      { ruleset: 'yara', detections: [detectionFixture({ id: 'b' })] },
    ]
    expect(displayedGroups(groups).map((group) => group.ruleset)).toEqual(['yara', 'custom'])
  })

  it('lists the most severe detection of a group first and keeps the order of equals', () => {
    const cape = displayedGroups(DETECTIONS_VIEW.groups).find((group) => group.ruleset === 'cape')!
    expect(cape.detections.map((detection) => detection.id)).toEqual([CAPE_RECON_ID, CAPE_DLL_ID])
  })

  it('keeps only the wanted detections and drops a group left empty', () => {
    const groups = displayedGroups(DETECTIONS_VIEW.groups, [SIGMA_ID, SURICATA_ID])
    expect(groups.map((group) => group.ruleset)).toEqual(['sigma', 'suricata'])
  })

  it('does not change the groups it is given', () => {
    const before = JSON.stringify(DETECTIONS_VIEW)
    displayedGroups(DETECTIONS_VIEW.groups)
    expect(JSON.stringify(DETECTIONS_VIEW)).toBe(before)
  })
})

describe('detectionById', () => {
  it('finds a detection in any group', () => {
    expect(detectionById(DETECTIONS_VIEW.groups, SURICATA_ID)?.name).toBe('ET MALWARE Possible beacon')
  })

  it('returns undefined for an unknown id', () => {
    expect(detectionById(DETECTIONS_VIEW.groups, 'nope')).toBeUndefined()
  })
})

describe('rulesetLabel', () => {
  it.each([
    ['sigma', 'SIGMA'],
    ['cape', 'CAPE'],
    ['yara', 'YARA'],
    ['suricata', 'SURICATA'],
    ['custom', 'CUSTOM'],
  ])('writes %s as %s', (ruleset, label) => {
    expect(rulesetLabel(ruleset)).toBe(label)
  })
})
