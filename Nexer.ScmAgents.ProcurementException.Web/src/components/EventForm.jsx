import { useMemo, useState } from "react";

function itemLabel(item) {
  const available = item.available_qty ?? item.available_quantity;
  const suffix = available == null ? "" : ` — available ${available}`;
  return `${item.item_id}${suffix}`;
}

function poLabel(po) {
  const bits = [
    po.po_id,
    po.line_num ? `line ${po.line_num}` : null,
    po.supplier_id ? `vendor ${po.supplier_id}` : null,
    po.expected_delivery_date ? `due ${po.expected_delivery_date}` : null,
  ].filter(Boolean);
  return bits.join(" — ");
}

export default function EventForm({ refData, onSubmit, loading }) {
  const eventType = refData?.event_type;
  const tenants = refData?.tenants ?? [];
  const items = refData?.items ?? [];
  const sample = refData?.event_sample ?? {};

  const initialItemId = sample.item_id ?? items[0]?.item_id ?? "";
  const [form, setForm] = useState({
    tenant_id: sample.tenant_id ?? tenants[0] ?? "",
    item_id: initialItemId,
    purchase_order_id: sample.purchase_order_id ?? "",
  });

  const purchaseOrders = useMemo(
    () => refData?.purchase_orders_by_item?.[form.item_id] ?? [],
    [refData, form.item_id]
  );

  const selectedPo =
    purchaseOrders.find((po) => po.po_id === form.purchase_order_id) ??
    purchaseOrders[0];

  const set = (key) => (e) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  function setItem(e) {
    const itemId = e.target.value;
    const firstPo = refData?.purchase_orders_by_item?.[itemId]?.[0];
    setForm((f) => ({
      ...f,
      item_id: itemId,
      purchase_order_id: firstPo?.po_id ?? "",
    }));
  }

  function submit(e) {
    e.preventDefault();
    onSubmit({
      event_type: eventType,
      tenant_id: form.tenant_id,
      item_id: form.item_id,
      supplier_id: selectedPo?.supplier_id ?? sample.supplier_id,
      purchase_order_id: form.purchase_order_id || selectedPo?.po_id,
      plant: selectedPo?.site_id ?? sample.plant,
      severity: sample.severity,
      context: {
        ...(sample.context ?? {}),
        use_case: "PROC-01",
        triggered_by: "event_simulation",
        objective: "Rank overdue PO lines by inventory coverage risk",
      },
    });
  }

  return (
    <form className="event-form" onSubmit={submit}>
      <p className="hint">
        Simulates PROC-01: rank overdue purchase order lines by inventory
        coverage risk using calculated receipt status, days late, days of cover
        and projected runout date.
      </p>

      <div className="hint">
        Event type: <strong>PROC-01 — Overdue PO Impact Prioritization</strong>
      </div>

      <label>
        Tenant
        <select value={form.tenant_id} onChange={set("tenant_id")}>
          {tenants.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>

      <label>
        Item
        <select value={form.item_id} onChange={setItem}>
          {items.map((i) => (
            <option key={i.item_id} value={i.item_id}>
              {itemLabel(i)}
            </option>
          ))}
        </select>
      </label>

      <label>
        Overdue PO
        <select value={form.purchase_order_id} onChange={set("purchase_order_id")}>
          {purchaseOrders.map((po) => (
            <option key={`${po.po_id}-${po.line_num ?? ""}`} value={po.po_id}>
              {poLabel(po)}
            </option>
          ))}
        </select>
      </label>

      {items.length === 0 && (
        <p className="hint">
          No calculated overdue purchase orders are available for PROC-01
          simulation.
        </p>
      )}

      <button
        className="submit-btn"
        type="submit"
        disabled={loading || !eventType || !form.tenant_id || !form.item_id || !selectedPo}
      >
        {loading ? "Analyzing…" : "Analyze PROC-01 Event"}
      </button>
    </form>
  );
}