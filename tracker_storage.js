// The only persistent data are whitelisted prediction records in this browser.
// All user data arrive through component.data, never HTML or JavaScript strings.
// Retain acknowledgements even if Streamlit reloads the renderer module.
const handled = globalThis.__realityCheckTrackerRequestsV1 ||= new Map();
const STORAGE_KEY = "reality-check.my-tracker.v1";
const MAX_ITEMS = 100;
const MAX_BYTES = 512 * 1024;

function readDocument() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return {schema_version: 1, items: []};
  if (new TextEncoder().encode(raw).length > MAX_BYTES) throw new Error("size");
  const doc = JSON.parse(raw);
  if (doc.schema_version !== 1 || !Array.isArray(doc.items) || doc.items.length > MAX_ITEMS)
    throw new Error("format");
  if (!doc.items.every(row => row && typeof row.tracker_id === "string"))
    throw new Error("format");
  return {schema_version: 1, items: doc.items};
}

export default function({data, setStateValue}) {
  const request = data.request_id;
  if (handled.has(request)) return;
  handled.set(request, true);
  if (handled.size > 200) handled.delete(handled.keys().next().value);
  try {
    const doc = readDocument();
    const op = data.operation;
    if (op) {
      // Read the current browser copy first, preserving changes from other tabs.
      const records = new Map(doc.items.map(row => [row.tracker_id, row]));
      if (op.kind === "upsert" || op.kind === "merge") {
        for (const row of op.items) {
          const existing = records.get(row.tracker_id);
          records.set(row.tracker_id, {...row, saved_at: existing?.saved_at || row.saved_at});
        }
      } else if (op.kind === "remove") records.delete(op.tracker_id);
      else throw new Error("operation");
      if (records.size > MAX_ITEMS) {
        setStateValue("reply", {request_id: request, error: "Your tracker is full (100 predictions). Remove one first."});
        return;
      }
      doc.items = Array.from(records.values());
      const raw = JSON.stringify(doc);
      if (new TextEncoder().encode(raw).length > MAX_BYTES) throw new Error("size");
      localStorage.setItem(STORAGE_KEY, raw);
      if (localStorage.getItem(STORAGE_KEY) !== raw) throw new Error("write");
    }
    setStateValue("reply", {request_id: request, items: doc.items, error: null});
  } catch (error) {
    setStateValue("reply", {request_id: request,
      error: "Your tracker could not be saved or read in this browser. Allow site storage and try again."});
  }
}
