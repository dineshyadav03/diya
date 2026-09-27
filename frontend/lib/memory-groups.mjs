// Grouping the Memory page's accepted facts by who they are about (docs/PERSON_MEMORY_DESIGN.md, D5,
// unit M3): "You" (facts with no person tag) first, then each named person alphabetically. A pure
// function, tested under Node (tests/test_memory_groups.py), the same way frontend/lib/api-failure.mjs
// is -- easier to prove right in isolation than by rendering the page.

const YOU_KEY = '\u0000you' // a NUL prefix: check_person_name forbids control characters, so no real
// person's name can ever equal this, even one literally typed as "you" (which gets its own group).

export function groupByPerson(facts) {
  const buckets = new Map()
  for (const fact of facts) {
    const key = fact.person || null
    if (!buckets.has(key)) buckets.set(key, [])
    buckets.get(key).push(fact)
  }
  const you = buckets.get(null) || []
  const names = [...buckets.keys()]
    .filter((key) => key !== null)
    .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
  const groups = you.length ? [{ key: YOU_KEY, label: 'You', facts: you }] : []
  return groups.concat(names.map((name) => ({ key: name, label: name, facts: buckets.get(name) })))
}
