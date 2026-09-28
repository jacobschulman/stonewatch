/* Shared availability loading for analytics. No private credentials are required. */
(function (root) {
    async function request(url, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 20000);
        try {
            const response = await fetch(url, { ...options, signal: controller.signal });
            if (!response.ok) throw new Error(`Data request failed (${response.status})`);
            // Keep the timeout active until the response body has arrived, too.
            return options.csv ? await response.text() : await response.json();
        } finally {
            clearTimeout(timer);
        }
    }

    function createLoader(parse) {
        let indexPromise;
        const cache = new Map();
        const base = '../data/availability/';

        async function index() {
            if (!indexPromise) {
                indexPromise = request(base + 'index.json', { cache: 'no-cache' }).then(value => {
                    if (value.version !== 1 || !Array.isArray(value.months)) throw new Error('Invalid availability index');
                    return value;
                }).catch(error => { indexPromise = undefined; throw error; });
            }
            return indexPromise;
        }

        async function month(entry) {
            if (!/^\d{4}-\d{2}\.csv$/.test(entry.file)) throw new Error('Invalid availability file');
            const key = `${entry.file}?v=${entry.sha256}`;
            if (!cache.has(key)) {
                const promise = request(base + key, { csv: true }).then(text => {
                    const parsed = parse(text, { header: true, skipEmptyLines: true });
                    if (!['slot_at_iso', 'seen_at_iso', 'service', 'party_size'].every(field => parsed.meta.fields?.includes(field)) || parsed.errors.length || parsed.data.length !== entry.rows) {
                        throw new Error('Incomplete availability data. Please retry.');
                    }
                    const rows = mergeSlots(parsed.data);
                    if (rows.length !== entry.rows) throw new Error('Invalid availability rows. Please retry.');
                    return rows;
                }).catch(error => { cache.delete(key); throw error; });
                cache.set(key, promise);
            }
            return cache.get(key);
        }

        async function load(range = '30', now = Date.now()) {
            const manifest = await index();
            const cutoff = range === 'all' ? -Infinity : now - Number(range) * 86400000;
            const entries = manifest.months.filter(entry => Date.parse(entry.last_seen) >= cutoff);
            // Bound parallel downloads for All Time. Recent views usually need only one or two months.
            const results = new Array(entries.length);
            let next = 0;
            async function worker() {
                while (next < entries.length) {
                    const position = next++;
                    results[position] = await month(entries[position]);
                }
            }
            await Promise.all(Array.from({ length: Math.min(4, entries.length) }, worker));
            return results.flat().filter(row => Date.parse(row.seen_at_iso) >= cutoff);
        }
        return { load };
    }

    function mergeSlots(...sources) {
        const slots = new Map();
        for (const rows of sources) {
            for (const row of rows) {
                const slotAt = Date.parse(row.slot_at_iso);
                const seenAt = Date.parse(row.seen_at_iso);
                const partySize = Number(row.party_size);
                if (!Number.isFinite(slotAt) || !Number.isFinite(seenAt) || !partySize || !row.service) continue;
                // Supabase emits UTC while CSV uses New York offsets for the same slot.
                const key = `${slotAt}|${partySize}|${row.service}|${row.merchant_id || '278278'}`;
                const existing = slots.get(key);
                if (!existing || seenAt < Date.parse(existing.seen_at_iso)) {
                    slots.set(key, {
                        ...row,
                        party_size: partySize,
                        lead_hours: Number(row.lead_hours) || 0,
                        lead_minutes: Number(row.lead_minutes) || 0,
                        hour_slot: Number(row.hour_slot)
                    });
                }
            }
        }
        return [...slots.values()];
    }

    const api = { createLoader, mergeSlots };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.StoneWatchData = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
