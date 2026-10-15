/* PharmaCare: owner GST report and staff role-based workspace. */
(() => {
  "use strict";
  const apiRoot = "/pharmacy/api/";
  const text = value => String(value ?? "");
  const money = value => new Intl.NumberFormat("en-IN", {
    style: "currency", currency: "INR"
  }).format(Number(value) || 0);
  const api = async (path, options = {}) => {
    const response = await fetch(apiRoot + path, {
      credentials: "same-origin", ...options,
      headers: {"Content-Type": "application/json", ...(options.headers || {})}
    });
    if (!response.ok) {
      let message = "Request failed: " + response.status;
      try { message = (await response.json()).detail || message; } catch (_) {}
      throw new Error(message);
    }
    return response.status === 204 ? null : response.json();
  };
  const element = (tag, label, cls) => {
    const el = document.createElement(tag);
    if (label !== undefined) el.textContent = text(label);
    if (cls) el.className = cls;
    return el;
  };
  const field = (name, label, type = "text") => {
    const wrapper = element("label", label, "field");
    const input = element("input");
    input.name = name;
    input.type = type;
    wrapper.appendChild(input);
    return wrapper;
  };
  const button = (label, handler, cls = "btn secondary") => {
    const b = element("button", label, cls);
    b.type = "button";
    b.addEventListener("click", handler);
    return b;
  };
  const table = (headers, rows) => {
    const wrapper = element("div", undefined, "tablewrap");
    const t = element("table"), head = element("thead"), body = element("tbody");
    const hrow = element("tr");
    headers.forEach(h => hrow.appendChild(element("th", h)));
    head.appendChild(hrow);
    rows.forEach(values => {
      const row = element("tr");
      values.forEach(v => row.appendChild(element("td", v)));
      body.appendChild(row);
    });
    t.append(head, body);
    wrapper.appendChild(t);
    return wrapper;
  };
  const panel = title => {
    const overlay = element("div", undefined, "modalback");
    overlay.style.zIndex = "9000";
    const sheet = element("section", undefined, "modal");
    sheet.style.width = "min(950px,100%)";
    sheet.appendChild(element("h2", title));
    sheet.appendChild(button("Close", () => overlay.remove()));
    overlay.appendChild(sheet);
    overlay.addEventListener("click", event => {
      if (event.target === overlay) overlay.remove();
    });
    document.body.appendChild(overlay);
    return sheet;
  };
  function gstReport() {
    const sheet = panel("GST, discounts & recorded returns");
    const form = element("form", undefined, "formgrid");
    form.append(field("start_date", "From", "date"), field("end_date", "To", "date"));
    const submit = element("button", "Generate", "btn");
    submit.type = "submit";
    form.appendChild(submit);
    const output = element("div", "Loading...", "panel");
    output.style.padding = "16px";
    sheet.append(form, output);
    const run = async () => {
      output.textContent = "Loading...";
      try {
        const params = new URLSearchParams();
        new FormData(form).forEach((v, k) => { if (v) params.set(k, v); });
        const data = await api("reports/gst-net?" + params.toString());
        output.replaceChildren(element("h3", "Net GST after recorded returns"));
        output.appendChild(table(
          ["Metric", "Recorded returns", "Net"],
          [["Taxable", "taxable"], ["CGST", "cgst"], ["SGST", "sgst"], ["IGST", "igst"]]
            .map(([name, key]) => [name, money(data.returns[key]), money(data.net[key])])
        ));
        output.appendChild(element("h3",
          "Total after recorded refunds: " +
          money(data.net.collected_less_recorded_refunds)));
        output.appendChild(element("p", data.warning));
        output.appendChild(element("h3", "Draft credit notes"));
        output.appendChild(table(["Draft", "Return", "Refund", "Reconciled"],
          data.draft_credit_notes.map(d => [
            d.draft_number, "#" + d.return_id, money(d.refund),
            d.reconciled ? "Yes" : "Requires review"
          ])));
      } catch (err) {
        output.textContent = "Could not load report: " + err.message;
      }
    };
    form.addEventListener("submit", event => { event.preventDefault(); run(); });
    run();
  }
  document.addEventListener("click", event => {
    const target = event.target.closest('[data-view="gst-report"]');
    if (!target || !document.body.classList.contains("authenticated")) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    gstReport();
  }, true);

  // This listener also supports staff screen restoration on page refresh.
  // Do not display the owner dashboard to a staff session.
  async function staffWorkspace(user) {
    if (document.getElementById("pcStaffWorkspace")) return;
    const role = user.role;
    const allowed = {
      manager: ["inventory", "sales", "returns", "customers", "purchasing", "reports"],
      pharmacist: ["inventory", "sales", "returns", "customers", "prescriptions"],
      cashier: ["inventory", "sales", "returns", "customers"],
      inventory: ["inventory", "purchasing"]
    }[role] || ["inventory"];
    const root = element("main", undefined, "pc-staff-workspace");
    root.id = "pcStaffWorkspace";
    root.style.cssText = "position:fixed;inset:0;z-index:99998;background:#f5f7fa;color:#182536;overflow:auto;padding:24px;";
    const shell = element("div");
    shell.style.cssText = "max-width:1100px;margin:auto";
    const header = element("header");
    header.style.cssText = "display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap";
    const heading = element("div");
    heading.append(element("h1", "PharmaCare Staff"), element("p", user.username + " — " + role));
    header.append(heading, button("Sign out", async () => {
      try { await api("logout", {method: "POST"}); } finally { location.reload(); }
    }));
    const nav = element("nav", undefined, "pharma-toolbar");
    nav.style.display = "flex";
    const content = element("section", "Loading...");
    content.style.cssText = "margin-top:24px;background:white;border-radius:12px;padding:20px";
    shell.append(header, nav, content);
    root.appendChild(shell);
    document.body.appendChild(root);
    const notify = error => { content.textContent = "Error: " + error.message; };
    const render = async name => {
      content.textContent = "Loading...";
      try {
        if (name === "inventory") {
          const rows = await api("staff/inventory");
          content.replaceChildren(element("h2", "Medicine batches"));
          content.appendChild(table(["Medicine", "Batch", "Stock", "Expiry", "Price"],
            rows.map(m => [m.name, m.batch_number, m.quantity,
              m.expiry_date, money(m.unit_price)])));
          return;
        }
        if (name === "sales") {
          const inventory = await api("staff/inventory");
          content.replaceChildren(element("h2", "New sale (FEFO)"));
          const form = element("form", undefined, "formgrid");
          const choose = element("select");
          choose.name = "medicine_id";
          inventory.filter(m => m.quantity > 0).forEach(m => {
            const option = element("option", m.name + " — " + m.batch_number);
            option.value = m.id;
            choose.appendChild(option);
          });
          const medicineLabel = element("label", "Medicine / batch", "field");
          medicineLabel.appendChild(choose);
          form.append(medicineLabel, field("quantity", "Quantity", "number"),
            field("gst_rate", "GST % (verified)", "number"),
            field("discount_amount", "Discount ₹", "number"));
          const quantity = form.elements.namedItem("quantity");
          quantity.min = "1"; quantity.step = "1"; quantity.required = true;
          const rate = form.elements.namedItem("gst_rate");
          rate.min = "0"; rate.max = "100"; rate.step = "0.01"; rate.value = "0";
          const discount = form.elements.namedItem("discount_amount");
          discount.min = "0"; discount.step = "0.01"; discount.value = "0";
          const status = element("p");
          const submit = element("button", "Complete sale", "btn");
          submit.type = "submit";
          form.append(submit, status);
          form.addEventListener("submit", async e => {
            e.preventDefault();
            submit.disabled = true;
            status.textContent = "Allocating FEFO batches...";
            try {
              const values = Object.fromEntries(new FormData(form).entries());
              const item = {
                medicine_id: Number(values.medicine_id),
                quantity: Number(values.quantity),
                gst_rate: values.gst_rate || "0",
                discount_amount: values.discount_amount || "0"
              };
              const plan = await api("sales/fefo-plan", {
                method: "POST", body: JSON.stringify({items: [item]})
              });
              if (!confirm("Confirm this sale and deduct stock?")) {
                status.textContent = "Cancelled"; return;
              }
              const sale = await api("sales", {
                method: "POST",
                body: JSON.stringify({items: plan.items, interstate: false})
              });
              status.textContent = "Invoice " + sale.invoice_number + " — " + money(sale.total);
            } catch (err) { status.textContent = err.message; }
            finally { submit.disabled = false; }
          });
          content.appendChild(form);
          return;
        }
        if (name === "returns") {
          const [sales, returns] = await Promise.all([api("sales"), api("returns")]);
          content.replaceChildren(element("h2", "Recorded returns"));
          content.appendChild(table(["Return", "Sale", "Refund obligation"],
            returns.map(r => [r.id, r.sale_id, money(r.refund_amount)])));
          content.appendChild(element("p", "Returns are recorded, not automatically paid or restocked."));
          const form = element("form", undefined, "formgrid");
          const choose = element("select");
          choose.name = "sale_id";
          sales.forEach(s => {
            const option = element("option", s.invoice_number || "Sale " + s.id);
            option.value = s.id;
            choose.appendChild(option);
          });
          const saleLabel = element("label", "Original sale", "field");
          saleLabel.appendChild(choose);
          const medicineLabel = element("label", "Medicine from selected sale", "field");
          const medicine = element("select");
          medicine.name = "medicine_id";
          medicineLabel.appendChild(medicine);
          const refreshMedicines = () => {
            medicine.replaceChildren();
            const sale = sales.find(s => s.id === Number(choose.value));
            if (sale) sale.items.forEach(i => {
              const option = element("option", i.medicine + " — " + i.batch_number);
              option.value = i.medicine_id;
              medicine.appendChild(option);
            });
          };
          choose.addEventListener("change", refreshMedicines);
          refreshMedicines();
          form.append(saleLabel, medicineLabel,
            field("quantity", "Return quantity", "number"),
            field("reason", "Return reason"));
          const qty = form.elements.namedItem("quantity");
          qty.min = "1"; qty.step = "1"; qty.required = true;
          const reason = form.elements.namedItem("reason");
          reason.minLength = 3; reason.required = true;
          const status = element("p");
          const submit = element("button", "Record return", "btn");
          submit.type = "submit";
          form.append(submit, status);
          form.addEventListener("submit", async e => {
            e.preventDefault();
            submit.disabled = true;
            try {
              const data = Object.fromEntries(new FormData(form).entries());
              if (!confirm("Record return? Payment and restocking will NOT occur.")) return;
              const record = await api("returns", {
                method: "POST",
                body: JSON.stringify({
                  sale_id: Number(data.sale_id),
                  reason: data.reason,
                  items: [{
                    medicine_id: Number(data.medicine_id),
                    quantity: Number(data.quantity)
                  }]
                })
              });
              status.textContent = "Recorded return #" + record.id + " — " +
                money(record.refund_amount);
            } catch (err) { status.textContent = err.message; }
            finally { submit.disabled = false; }
          });
          content.appendChild(form);
          return;
        }
        const paths = {
          customers: "customers", purchasing: "purchase-orders",
          prescriptions: "prescriptions", reports: "finance/summary"
        };
        const data = await api(paths[name]);
        content.replaceChildren(element("h2", name[0].toUpperCase() + name.slice(1)));
        const rows = Array.isArray(data) ? data : null;
        if (name === "customers") {
          content.appendChild(table(
            ["Name", "Phone", "Email"],
            rows.map(c => [c.name, c.phone || "—", c.email || "—"])
          ));
          const form = element("form", undefined, "formgrid");
          form.append(
            field("name", "Customer name"),
            field("phone", "Phone"),
            field("email", "Email")
          );
          form.elements.namedItem("name").required = true;
          const notice = element("p");
          const submit = element("button", "Add customer", "btn");
          submit.type = "submit";
          form.append(submit, notice);
          form.addEventListener("submit", async e => {
            e.preventDefault();
            submit.disabled = true;
            try {
              const values = Object.fromEntries(new FormData(form).entries());
              await api("customers", {
                method: "POST", body: JSON.stringify(values)
              });
              await render("customers");
            } catch (err) { notice.textContent = err.message; }
            finally { submit.disabled = false; }
          });
          content.appendChild(form);
        } else if (name === "purchasing") {
          content.appendChild(element("p",
            "Review purchase orders. Receiving stock remains restricted to authorized inventory roles."
          ));
          content.appendChild(table(
            ["Order", "Supplier", "Status", "Created"],
            rows.map(o => [
              "#" + o.id, o.supplier_name || o.supplier_id || "—",
              o.status || "—", o.created_at || "—"
            ])
          ));
        } else if (name === "prescriptions") {
          content.appendChild(element("p",
            "Prescription metadata access is limited to authorized pharmacist or manager roles. Do not use real patient data without HTTPS and compliance review."
          ));
          content.appendChild(table(
            ["Record", "Customer", "Date", "Items"],
            rows.map(p => [
              "#" + p.id, p.customer_name || p.customer_id || "—",
              p.created_at || "—", Array.isArray(p.items) ? p.items.length : "—"
            ])
          ));
        } else if (name === "reports") {
          content.appendChild(table(
            ["Metric", "Value"],
            [
              ["Recorded sales", data.sales_count || 0],
              ["Gross sales", money(data.gross_sales)],
              ["Recorded refund obligations", money(data.recorded_refunds)],
              ["Sales after recorded refunds", money(data.sales_after_recorded_refunds)],
              ["Received purchase orders", money(data.received_purchase_order_value)],
              ["Pending purchase orders", money(data.pending_purchase_order_value)]
            ]
          ));
          content.appendChild(element("p", data.note ||
            "Profit is not yet calculated from cost of goods sold."));
        }
      } catch (err) { notify(err); }
    };
    allowed.forEach(name => nav.appendChild(button(
      name[0].toUpperCase() + name.slice(1), () => render(name)
    )));
    render("inventory");
  }
  document.addEventListener("pharmacare-staff-login", e => staffWorkspace(e.detail));
  api("auth").then(auth => {
    if (auth.authenticated && auth.role && auth.role !== "owner") {
      staffWorkspace(auth);
    }
  }).catch(() => {});
})();
