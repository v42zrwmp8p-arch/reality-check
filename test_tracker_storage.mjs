// Frontend contract checks with simulated localStorage and Streamlit callbacks.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('./tracker_storage.js', import.meta.url), 'utf8');
let values = new Map();
globalThis.localStorage = {
  getItem: key => values.get(key) ?? null,
  setItem: (key, value) => { values.set(key, String(value)); },
};
let generation = 0;
async function newPage() {
  return (await import('data:text/javascript;base64,' + Buffer.from(source + `\n// page ${generation++}`).toString('base64'))).default;
}
const storageKey = 'reality-check.my-tracker.v1';
const row = {tracker_id:'fixture-1', symbol:'NVDA', asset:'Nvidia', saved_at:'2026-11-14T00:00:00+00:00'};
let calls = [];
const invoke = (render, request, operation=null) => {
  const before = calls.length;
  render({data:{request_id:request, operation}, setStateValue:(name, reply)=>calls.push(structuredClone(reply))});
  return calls.length > before ? calls.at(-1) : null;
};
const page = await newPage();
assert.deepEqual(invoke(page, 'initial').items, []);
assert.equal(values.size, 0, 'reading an empty tracker must not write');
assert.equal(invoke(page, 'initial'), null, 'ordinary reruns must not create feedback loops');
assert.equal(invoke(page, 'save', {kind:'upsert', items:[row]}).items.length, 1);
assert.equal(invoke(page, 'save', {kind:'upsert', items:[row]}), null);
const reopened = await newPage();
assert.equal(invoke(reopened, 'reopen').items[0].symbol, 'NVDA');
const secondTab = await newPage();
invoke(secondTab, 'other-save', {kind:'upsert', items:[{...row, tracker_id:'fixture-2', symbol:'CROX'}]});
const merged = invoke(page, 'update', {kind:'upsert', items:[{...row, target_value:3, saved_at:'changed'}]});
assert.equal(merged.items.length, 2, 'updates preserve records added by another tab');
assert.equal(merged.items[0].saved_at, row.saved_at);
assert.equal(merged.items[0].target_value, 3);
const backup = JSON.stringify(JSON.parse(values.get(storageKey)));
const otherBrowserStore = new Map();
const originalStore = values;
values = otherBrowserStore;
const otherBrowser = await newPage();
assert.deepEqual(invoke(otherBrowser, 'isolated').items, []);
assert.equal(invoke(otherBrowser, 'restore', {kind:'merge', items:JSON.parse(backup).items}).items.length, 2);
invoke(otherBrowser, 'remove', {kind:'remove', tracker_id:'fixture-1'});
assert.equal(JSON.parse(values.get(storageKey)).items.length, 1);
values = originalStore;
assert.equal(JSON.parse(values.get(storageKey)).items.length, 2, 'removal in another browser must stay separate');
values.set(storageKey, '{broken');
assert.ok(invoke(page, 'corrupt-read').error);
assert.equal(values.get(storageKey), '{broken', 'corrupt records must not be overwritten');
values.clear();
const full = Array.from({length:100}, (_,i)=>({...row, tracker_id:'id-'+i}));
values.set(storageKey, JSON.stringify({schema_version:1, items:full}));
assert.ok(invoke(page, 'full', {kind:'upsert', items:[row]}).error);
assert.equal(JSON.parse(values.get(storageKey)).items.length,100);
globalThis.localStorage.setItem = () => { throw new Error('simulated storage denied'); };
assert.ok(invoke(page, 'denied', {kind:'remove', tracker_id:'id-1'}).error);
assert.equal(JSON.parse(values.get(storageKey)).items.length,100, 'a failed write cannot be acknowledged as saved');
console.log('Frontend storage contract passed: save, reopen, isolation, merge, remove, limits and failed writes.');
