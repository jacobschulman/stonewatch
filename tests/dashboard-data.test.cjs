const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mergeSlots, createLoader } = require('../dashboard/data.js');
const fs = require('node:fs');
const vm = require('node:vm');

test('merges time-zone equivalents and retains the first sighting and metrics', () => {
    const slot = { slot_at_iso: '2026-09-28T18:00:00-04:00', seen_at_iso: '2026-09-28T12:00:00Z', party_size: '2', service: 'Dinner', lead_hours: '10' };
    const rows = mergeSlots([slot], [{ ...slot, slot_at_iso: '2026-09-28T22:00:00Z', seen_at_iso: '2026-09-27T22:00:00Z', lead_hours: 24 }, { ...slot, party_size: 4 }]);
    assert.equal(rows.length, 2);
    assert.equal(rows[0].lead_hours, 24);
    assert.equal(rows[0].party_size, 2);
    assert.equal(mergeSlots([{ ...slot, slot_at_iso: 'bad' }]).length, 0);
});

test('analytics starts after setup for returning visitors and handles empty history', async () => {
    const html = fs.readFileSync(require.resolve('../dashboard/stonewatch-dashboard.html'), 'utf8');
    const source = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]).join('\n');
    for (const authenticated of [false, true]) {
        const elements = new Map();
        function element(id) {
            if (!elements.has(id)) elements.set(id, { innerHTML: '', classList: { add() {}, remove() {}, toggle() {} }, addEventListener(name, fn) { this[name] = fn; }, focus() {} });
            return elements.get(id);
        }
        let loads = 0;
        const context = vm.createContext({
            console, setTimeout,
            sessionStorage: { getItem: () => authenticated ? 'true' : null, setItem() {} },
            document: { getElementById: element, querySelector: () => null },
            Chart: Object.assign(class { constructor(el, config) { this.data = config.data; } }, { defaults: { font: {} } }),
            Papa: { parse() {} },
            StoneWatchData: { createLoader() { return { async load() { loads++; return []; } }; } }
        });
        vm.runInContext(source, context);
        if (!authenticated) {
            assert.equal(loads, 0);
            // Use the configured password within the test; no live service or credentials are accessed.
            element('passwordInput').value = vm.runInContext('CORRECT_PASSWORD', context);
            element('passwordInput').keydown({ key: 'Enter' });
        }
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(loads, 1);
        assert.match(element('app').innerHTML, /Slots Found/);
        assert.match(element('app').innerHTML, /id="stat-total">0</);
        assert.match(element('low-data-warning').innerHTML, /No data for selected filters/);
    }
});

test('recent views load only overlapping months; All Time downloads and caches the rest', async () => {
    const originalFetch = global.fetch;
    const fields = ['slot_at_iso', 'seen_at_iso', 'service', 'party_size'];
    const rows = [
        { slot_at_iso: '2026-01-28T22:00:00Z', seen_at_iso: '2026-01-28T12:00:00Z', service: 'Dinner', party_size: '2' },
        { slot_at_iso: '2026-09-28T22:00:00Z', seen_at_iso: '2026-09-28T12:00:00Z', service: 'Dinner', party_size: '2' }
    ];
    const manifest = { version: 1, months: rows.map((row, i) => ({ file: `${i ? '2026-09' : '2026-01'}.csv`, sha256: 'test', rows: 1, last_seen: row.seen_at_iso })) };
    const urls = [];
    try {
        global.fetch = async url => {
            urls.push(url);
            return { ok: true, json: async () => manifest, text: async () => url.includes('2026-01') ? '0' : '1' };
        };
        const loader = createLoader(text => ({ data: [rows[Number(text)]], meta: { fields }, errors: [] }));
        const now = Date.parse('2026-09-28T14:00:00Z');
        assert.equal((await loader.load('30', now)).length, 1);
        assert.deepEqual(urls, ['../data/availability/index.json', '../data/availability/2026-09.csv?v=test']);
        assert.equal((await loader.load('all', now)).length, 2);
        assert.equal(urls.length, 3);
        assert.equal((await loader.load('7', now)).length, 1);
        assert.equal(urls.length, 3);
    } finally { global.fetch = originalFetch; }
});

test('incomplete monthly downloads fail visibly and can be retried without stale cache', async () => {
    const originalFetch = global.fetch;
    const fields = ['slot_at_iso', 'seen_at_iso', 'service', 'party_size'];
    const row = { slot_at_iso: '2026-09-28T22:00:00Z', seen_at_iso: '2026-09-28T12:00:00Z', service: 'Dinner', party_size: '2' };
    const manifest = { version: 1, months: [{ file: '2026-09.csv', sha256: 'test', rows: 1, last_seen: row.seen_at_iso }] };
    let broken = true;
    try {
        global.fetch = async () => ({ ok: true, json: async () => manifest, text: async () => 'csv' });
        const loader = createLoader(() => ({ data: broken ? [] : [row], meta: { fields }, errors: [] }));
        await assert.rejects(loader.load('all'), /Incomplete/);
        broken = false;
        assert.equal((await loader.load('all')).length, 1);
        global.fetch = async () => { throw new Error('offline'); };
        await assert.rejects(createLoader(() => {}).load(), /offline/);
    } finally { global.fetch = originalFetch; }
});

test('status reads both static histories and retains their event details on refresh', async () => {
    const html = fs.readFileSync(require.resolve('../dashboard/status.html'), 'utf8');
    const source = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]).join('\n');
    const requests = [];
    const context = vm.createContext({
        console, AbortSignal,
        document: { getElementById: () => ({ addEventListener() {}, focus() {} }) },
        sessionStorage: { getItem: () => null },
        fetch: async url => {
            requests.push(url);
            return { ok: true, json: async () => ({ runs: [{ id: url, started_at: '2026-09-28T12:00:00Z', events: [{ action: 'NOTIFIED' }] }] }) };
        }
    });
    vm.runInContext(source, context);
    for (let refresh = 0; refresh < 2; refresh++) {
        const runs = await vm.runInContext('fetchRuns()', context);
        assert.equal(runs.length, 2);
        assert.equal((await vm.runInContext('fetchEventsForRun("base-runs.json")', context))[0].action, 'NOTIFIED');
    }
    assert.deepEqual(requests, ['base-runs.json', 'vip-runs.json', 'base-runs.json', 'vip-runs.json']);
});
