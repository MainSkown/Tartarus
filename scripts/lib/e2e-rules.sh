# Assertions for scripts/e2e.sh on the Sigma rules: the Rules endpoint, the one alert the benign
# sample's registry write raises through the Tartarus-authored rule, and that disabling the rule and
# re-ingesting the analysis removes the alert. Sourced after e2e-api.sh, e2e-views.sh and
# e2e-query.sh (whose query_assert runs the search blocks here).

SELFTEST_RULE_ID=6c17e2ec-0203-4f72-8760-b1b2a72336db
SELFTEST_REGISTRY_SUFFIX='\Software\Tartarus\SelfTest'
MIN_SHIPPED_RULES=60
# "1" from the moment this script disables the rule until it has enabled it again; the cleanup trap
# reads it, so a run that dies in between cannot leave the rule off for the next one.
SELFTEST_RULE_DISABLED=0

# --- the Rules endpoint -------------------------------------------------------------------------

rules_endpoint_lists_the_shipped_set_and_the_selftest_rule() {
    http GET /api/rules
    [[ $HTTP_CODE == 200 ]] || { echo "GET /api/rules answered $HTTP_CODE"; return 1; }
    json_assert <<PY
shipped = [rule for rule in v if "/default/" in rule["path"]]
assert len(shipped) >= $MIN_SHIPPED_RULES, f"{len(shipped)} shipped rules listed, at least $MIN_SHIPPED_RULES are shipped"
not_valid = [f"{rule['id']} is {rule['validity']}: {rule['error']}" for rule in shipped if rule["validity"] != "valid"]
assert not not_valid, f"{len(not_valid)} of {len(shipped)} shipped rules are not valid: " + "; ".join(not_valid[:5])
selftest = [rule for rule in v if rule["id"] == "$SELFTEST_RULE_ID"]
assert selftest, "no rule $SELFTEST_RULE_ID among the {len(v)} listed"
rule = selftest[0]
assert rule["validity"] == "valid", f"the self-test rule is {rule['validity']}: {rule['error']}"
assert rule["enabled"] is True, "the self-test rule is disabled"
detail = f"{len(shipped)} shipped rules, all valid, and the self-test rule enabled ({len(v)} listed)"
PY
}

# --- one alert in the final index ---------------------------------------------------------------

selftest_alert_is_single_and_names_the_registry_write() { # id
    query_assert "$1" <<PY
rule = "$SELFTEST_RULE_ID"
every_sigma_alert = total_of(query="rule.ruleset:sigma")
found = search(query=f'rule.ruleset:sigma AND rule.id:"{rule}"', size=50)
assert found["total"] == 1, f"{found['total']} alerts of the rule in the index (wanted 1; {every_sigma_alert} Sigma alerts in all)"
alert = found["events"][0]
assert alert["kind"] == "alert" and alert["rule_ruleset"] == "sigma", f"the event is kind {alert['kind']}, ruleset {alert['rule_ruleset']}"
assert alert["lane"] == "registry", f"the alert is in lane {alert['lane']}"
document = detail_of(alert["id"])
assert document["source"]["rule"]["id"] == rule, f"the alert's rule is {document['source']['rule']['id']}"
references = document["related"]["references"]
assert references["total"] == 1, f"the alert names {references['total']} events"
trigger = references["items"][0]
assert trigger["action"] == "reg-value-set", f"the event it names is {trigger['action']}, not reg-value-set"
assert (trigger["registry_path"] or "").endswith(r"$SELFTEST_REGISTRY_SUFFIX"), f"the registry path is {trigger['registry_path']}"
detail = f"one alert, naming {trigger['action']} on {trigger['registry_path']} ({every_sigma_alert} Sigma alerts in all)"
PY
}

selftest_detection_is_in_the_sigma_group() { # id
    view_assert "$1" detections <<PY
status, rule = api("GET", "/api/rules/$SELFTEST_RULE_ID")
assert status == 200, f"GET /api/rules/$SELFTEST_RULE_ID answered {status}"
groups = {group["ruleset"]: group for group in v["groups"]}
assert "sigma" in groups, f"no sigma group among {sorted(groups)}"
mine = [d for d in groups["sigma"]["detections"] if d["name"] == rule["title"]]
assert len(mine) == 1, f"{len(mine)} detections named {rule['title']!r} in the sigma group"
actions = [event["action"] for event in mine[0]["related_events"]]
assert actions == ["reg-value-set"], f"its related events are {actions}"
detail = f"{len(groups['sigma']['detections'])} Sigma detections, one of them the self-test rule's"
PY
}

# The hits endpoint leaves a rule with no hit out, so "absent" is what a rule that never fired reports.
rule_hits_in_analysis() { # id -> count or "absent"
    http GET "/api/analyses/$1/rules/hits"
    [[ $HTTP_CODE == 200 ]] || { echo "GET rules/hits answered $HTTP_CODE" >&2; return 1; }
    body | json_eval 'next((hit["count"] for hit in v if hit["rule_id"].lower() == "'"$SELFTEST_RULE_ID"'"), "absent")'
}

selftest_alert_count() { # id
    http POST "/api/analyses/$1/events/search" -H 'content-type: application/json' \
        -d "{\"query\": \"rule.ruleset:sigma AND rule.id:\\\"$SELFTEST_RULE_ID\\\"\", \"size\": 1}"
    [[ $HTTP_CODE == 200 ]] || { echo "the search answered $HTTP_CODE: $(body)" >&2; return 1; }
    body | json_field .total
}

rule_detection_state_is() { # id alerts hits
    local alerts hits
    alerts=$(selftest_alert_count "$1") && hits=$(rule_hits_in_analysis "$1") || return 1
    [[ $alerts == "$2" ]] || { echo "$alerts alerts of the rule in the final index (wanted $2)"; return 1; }
    [[ $hits == "$3" ]] || { echo "hits report $hits for the rule (wanted $3)"; return 1; }
    echo "$alerts alerts, hits $hits"
}

rule_has_one_detection() { rule_detection_state_is "$1" 1 1; }
rule_has_no_detection() { rule_detection_state_is "$1" 0 absent; }

# --- disabling the rule -------------------------------------------------------------------------

rule_enabled_is() { # id true|false
    http GET "/api/rules/$1"
    [[ $HTTP_CODE == 200 ]] || { echo "GET /api/rules/$1 answered $HTTP_CODE"; return 1; }
    local enabled
    enabled=$(body | json_field .enabled)
    [[ ${enabled,,} == "$2" ]] || { echo "enabled is $enabled"; return 1; }
    echo "enabled is $enabled"
}

set_rule_enabled() { # id true|false
    http PATCH "/api/rules/$1" -H 'content-type: application/json' -d "{\"enabled\": $2}"
    [[ $HTTP_CODE == 200 ]] || { echo "PATCH answered $HTTP_CODE: $(body)"; return 1; }
    rule_enabled_is "$1" "$2"
}

reingest_and_wait() { # id
    local answer
    answer=$(reingest_answers "$1" 200) || { echo "$answer"; return 1; }
    wait_for_status "$1" done "$ANALYSIS_TIMEOUT"
}

# Called directly, never through `check`, so that the flag it clears survives.
restore_selftest_rule() {
    [[ $SELFTEST_RULE_DISABLED == 1 ]] || return 0
    local answer
    answer=$(set_rule_enabled "$SELFTEST_RULE_ID" true) || { echo "$answer" >&2; return 1; }
    SELFTEST_RULE_DISABLED=0
}

check_disabling_removes_the_detection() { # id
    local id=$1
    SELFTEST_RULE_DISABLED=1
    check "(k) PATCH /api/rules/$SELFTEST_RULE_ID disables the rule and it stays disabled" set_rule_enabled "$SELFTEST_RULE_ID" false &&
        check "(k) re-ingesting analysis $id with the rule disabled ends done" reingest_and_wait "$id" &&
        check "(k) with the rule disabled, the final index has 0 alerts of it and the hits endpoint omits it" rule_has_no_detection "$id"
    # Whatever failed above, the rule goes back on before anything else runs.
    restore_selftest_rule && ok "(k) the rule is enabled again" || fail "(k) the rule could not be enabled again; the cleanup tries once more"
    check "(k) GET /api/rules/$SELFTEST_RULE_ID says the rule is enabled" rule_enabled_is "$SELFTEST_RULE_ID" true
    check "(k) re-ingesting analysis $id with the rule enabled ends done" reingest_and_wait "$id" &&
        check "(k) enabling the rule and re-ingesting restores its one alert and its hit" rule_has_one_detection "$id"
}

# --- all of it ----------------------------------------------------------------------------------

check_sigma_rules() { # id
    local id=$1
    check "(k) GET /api/rules lists at least $MIN_SHIPPED_RULES shipped rules, all valid, and the enabled self-test rule" \
        rules_endpoint_lists_the_shipped_set_and_the_selftest_rule
    check "(k) the final index has exactly one Sigma alert of the self-test rule, naming the registry write" \
        selftest_alert_is_single_and_names_the_registry_write "$id"
    check "(k) /detections has the self-test rule's detection in its sigma group" selftest_detection_is_in_the_sigma_group "$id"
    check "(k) /rules/hits counts the rule once" rule_has_one_detection "$id"
    check_disabling_removes_the_detection "$id"
}
