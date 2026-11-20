/* ROSA storefront scripts. No secrets live here: prices, totals and payment
   verification are all decided by the Django backend. */
(function () {
  "use strict";

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var csrf = function () { var m = $('meta[name="csrf-token"]'); return m ? m.content : ""; };

  /* ---------- toasts ---------- */
  function toast(msg, kind) {
    var box = $("#toasts"); if (!box) return;
    var el = document.createElement("div");
    el.className = "toast toast--" + (kind || "info"); el.textContent = msg; el.setAttribute("role", "status");
    box.appendChild(el); dismiss(el, 3800);
  }
  function dismiss(el, ms) {
    setTimeout(function () { el.classList.add("is-leaving"); setTimeout(function () { el.remove(); }, 320); }, ms);
  }
  $$("#toasts .toast").forEach(function (t) { dismiss(t, 4500); });

  /* ---------- fetch helper ---------- */
  function post(url, body, isJson) {
    var headers = { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" };
    if (isJson) headers["Content-Type"] = "application/json";
    return fetch(url, { method: "POST", headers: headers, body: body, credentials: "same-origin" })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d._status = r.status; return d; }); });
  }
  function form(data) { var f = new FormData(); Object.keys(data).forEach(function (k) { f.append(k, data[k]); }); return f; }
  function setCount(sel, n) { $$(sel).forEach(function (b) { b.textContent = n; b.hidden = !n; }); }

  /* ---------- header: mobile menu + dropdown taps ---------- */
  var menuBtn = $("[data-menu-toggle]");
  if (menuBtn) menuBtn.addEventListener("click", function () { document.body.classList.toggle("menu-open"); });
  document.addEventListener("click", function (e) {
    var toggle = e.target.closest("[data-dd-toggle]");
    if (toggle) {
      var dd = toggle.closest(".dd"); var open = dd.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open); return;
    }
    if (window.matchMedia("(max-width:900px)").matches) {
      var chev = e.target.closest(".nav__links .dd > a");
      if (chev && chev.nextElementSibling && !chev.parentElement.classList.contains("open")) {
        e.preventDefault(); chev.parentElement.classList.add("open"); return;
      }
    }
    if (!e.target.closest(".dd")) $$(".dd.open").forEach(function (d) { d.classList.remove("open"); });
  });

  /* ---------- trending filter ---------- */
  var chips = $$("[data-filter]");
  if (chips.length) {
    var cards = $$("[data-trending] .card"); var empty = $(".filter-empty");
    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        chips.forEach(function (c) { c.classList.toggle("is-active", c === chip); });
        var f = chip.dataset.filter, shown = 0;
        cards.forEach(function (card) {
          var hide = f !== "all" && card.dataset.cat !== f;
          card.classList.toggle("is-hidden", hide); if (!hide) shown++;
        });
        if (empty) empty.hidden = shown > 0;
      });
    });
  }

  /* ---------- listing filters (mobile) ---------- */
  var ft = $("[data-filter-toggle]");
  if (ft) ft.addEventListener("click", function () { $("[data-filters]").classList.toggle("is-open"); });

  /* ---------- wishlist ---------- */
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-wish]"); if (!b) return;
    e.preventDefault();
    post(b.dataset.wish ? "/wishlist/toggle/" : "", form({ product_id: b.dataset.wish })).then(function (d) {
      if (d._status === 401 && d.login_url) { toast(d.message || "Log in to save items.", "info"); setTimeout(function () { location.href = d.login_url; }, 900); return; }
      if (!d.ok) { toast(d.message || "Something went wrong.", "error"); return; }
      $$('[data-wish="' + b.dataset.wish + '"]').forEach(function (x) { x.classList.toggle("is-on", d.added); x.setAttribute("aria-pressed", d.added); });
      setCount("[data-wishlist-count]", d.count); toast(d.message, "success");
    });
  });

  /* ---------- add to bag ---------- */
  function addToBag(fd, btn) {
    if (btn) btn.classList.add("is-loading");
    return post("/bag/add/", fd).then(function (d) {
      if (btn) btn.classList.remove("is-loading");
      if (!d.ok) { toast(d.message || "Couldn't add that item.", "error"); return d; }
      setCount("[data-cart-count]", d.count);
      if (d.redirect) { location.href = d.redirect; return d; }
      toast(d.message, "success"); return d;
    }).catch(function () { if (btn) btn.classList.remove("is-loading"); toast("Network problem. Please try again.", "error"); });
  }
  document.addEventListener("click", function (e) {
    var q = e.target.closest("[data-quick-add]"); if (!q) return;
    e.preventDefault(); addToBag(form({ product_id: q.dataset.quickAdd, quantity: 1 }), q);
  });

  /* ---------- product page ---------- */
  var box = $("[data-buybox]");
  if (box) {
    var qty = $("[data-qty] input", box);
    $("[data-qty-minus]", box).addEventListener("click", function () { qty.value = Math.max(1, (+qty.value || 1) - 1); });
    $("[data-qty-plus]", box).addEventListener("click", function () { var max = +qty.max || 99; qty.value = Math.min(max, (+qty.value || 1) + 1); });
    box.addEventListener("submit", function (e) {
      e.preventDefault(); if (!box.reportValidity()) return;
      addToBag(new FormData(box), $("[data-add-to-bag]", box));
    });
    var buy = $("[data-buy-now]", box);
    if (buy) buy.addEventListener("click", function () {
      if (!box.reportValidity()) return;
      var fd = new FormData(box); fd.append("buy_now", "1"); addToBag(fd, buy);
    });
  }

  /* ---------- gallery ---------- */
  var gal = $("[data-gallery]");
  if (gal) {
    var main = $("[data-main]", gal), stage = $("[data-stage]", gal), thumbs = $$("[data-thumb]", gal), cur = 0;
    function show(i) {
      if (!thumbs.length) return; cur = (i + thumbs.length) % thumbs.length;
      main.classList.add("is-swapping");
      setTimeout(function () { main.src = thumbs[cur].dataset.thumb; main.classList.remove("is-swapping"); }, 120);
      thumbs.forEach(function (t, n) { t.classList.toggle("is-active", n === cur); });
    }
    thumbs.forEach(function (t, i) { t.addEventListener("click", function () { show(i); }); });
    var p = $("[data-prev]", gal), n = $("[data-next]", gal);
    if (p) p.addEventListener("click", function (e) { e.stopPropagation(); show(cur - 1); });
    if (n) n.addEventListener("click", function (e) { e.stopPropagation(); show(cur + 1); });
    if (stage && window.matchMedia("(hover:hover)").matches) {
      stage.addEventListener("mouseenter", function () { stage.classList.add("is-zoom"); });
      stage.addEventListener("mouseleave", function () { stage.classList.remove("is-zoom"); });
      stage.addEventListener("mousemove", function (e) {
        var r = stage.getBoundingClientRect();
        main.style.setProperty("--zx", ((e.clientX - r.left) / r.width * 100) + "%");
        main.style.setProperty("--zy", ((e.clientY - r.top) / r.height * 100) + "%");
      });
    }
  }

  /* ---------- newsletter ---------- */
  var nl = $("[data-newsletter]");
  if (nl) nl.addEventListener("submit", function (e) {
    e.preventDefault();
    post(nl.action, new FormData(nl)).then(function (d) {
      toast(d.message || "Something went wrong.", d.ok ? "success" : "error"); if (d.ok) nl.reset();
    });
  });

  /* ---------- checkout + Razorpay ---------- */
  var co = $("[data-checkout]");
  if (co) {
    var newAddr = $("[data-newaddr]", co), err = $("[data-checkout-error]", co), pay = $("[data-pay]", co);
    function syncAddr() {
      var sel = co.querySelector('input[name="address_id"]:checked');
      newAddr.hidden = !(sel && sel.value === "new");
    }
    $$('input[name="address_id"]', co).forEach(function (r) { r.addEventListener("change", syncAddr); });
    function showErr(m) { err.textContent = m; err.hidden = false; pay.classList.remove("is-loading"); }

    co.addEventListener("submit", function (e) {
      e.preventDefault(); err.hidden = true; pay.classList.add("is-loading");
      post(co.dataset.createUrl, new FormData(co)).then(function (d) {
        if (!d.ok) { showErr(d.message || "We couldn't start the payment."); return; }
        if (typeof Razorpay === "undefined") { showErr("Payment window failed to load. Check your connection and retry."); return; }
        var rz = new Razorpay({
          key: d.key, amount: d.amount, currency: d.currency, name: d.store_name,
          description: "Order " + d.order_number, order_id: d.razorpay_order_id, prefill: d.prefill,
          theme: { color: "#E58A24" },
          modal: { ondismiss: function () { pay.classList.remove("is-loading"); } },
          handler: function (resp) {
            pay.classList.add("is-loading");
            post(d.verify_url, form({
              razorpay_order_id: resp.razorpay_order_id, razorpay_payment_id: resp.razorpay_payment_id,
              razorpay_signature: resp.razorpay_signature
            })).then(function (v) {
              if (v.redirect) { location.href = v.redirect; } else { showErr(v.message || "Payment could not be verified."); }
            });
          }
        });
        rz.on("payment.failed", function (resp) {
          post(d.failed_url, form({ razorpay_order_id: d.razorpay_order_id, reason: (resp.error && resp.error.description) || "Payment failed" }))
            .then(function (f) { if (f.redirect) location.href = f.redirect; });
        });
        rz.open();
      }).catch(function () { showErr("Network problem. Please try again."); });
    });
  }

  /* ---------- AI assistant ---------- */
  var ai = $("[data-ai]");
  if (ai) {
    var panel = $(".ai__panel", ai), log = $("[data-ai-log]", ai), fm = $("[data-ai-form]", ai), hist = [];
    function bubble(text, cls) { var b = document.createElement("div"); b.className = "ai__msg " + cls; b.textContent = text; log.appendChild(b); log.scrollTop = log.scrollHeight; return b; }
    function cardsFor(list) {
      var wrap = document.createElement("div"); wrap.className = "ai__prods";
      list.forEach(function (p) {
        var a = document.createElement("a"); a.className = "ai__prod"; a.href = p.url;
        a.innerHTML = (p.image ? '<img alt="">' : '<div class="ph"></div>') + "<span></span>";
        if (p.image) a.querySelector("img").src = p.image;
        a.querySelector("span").textContent = p.name + " · " + p.price; wrap.appendChild(a);
      });
      log.appendChild(wrap); log.scrollTop = log.scrollHeight;
    }
    $("[data-ai-open]", ai).addEventListener("click", function () { panel.hidden = !panel.hidden; if (!panel.hidden) fm.message.focus(); });
    $("[data-ai-close]", ai).addEventListener("click", function () { panel.hidden = true; });
    fm.addEventListener("submit", function (e) {
      e.preventDefault(); var text = fm.message.value.trim(); if (!text) return;
      bubble(text, "ai__msg--me"); fm.message.value = "";
      var wait = bubble("Thinking…", "ai__msg--bot");
      post(ai.dataset.chatUrl, JSON.stringify({ message: text, history: hist }), true).then(function (d) {
        wait.remove();
        if (!d.ok) { bubble(d.message || "Something went wrong.", "ai__msg--err"); return; }
        bubble(d.reply, "ai__msg--bot"); if (d.products && d.products.length) cardsFor(d.products);
        hist.push({ role: "user", content: text }, { role: "assistant", content: d.reply }); hist = hist.slice(-8);
      }).catch(function () { wait.remove(); bubble("Network problem. Please try again.", "ai__msg--err"); });
    });

    var cmp = $("[data-compare]");
    if (cmp) cmp.addEventListener("click", function () {
      var out = $("[data-compare-out]"); out.hidden = false; out.textContent = "Comparing…"; cmp.classList.add("is-loading");
      post(ai.dataset.compareUrl, JSON.stringify({ slugs: JSON.parse(cmp.dataset.slugs) }), true).then(function (d) {
        cmp.classList.remove("is-loading"); out.textContent = d.ok ? d.reply : (d.message || "Couldn't compare right now.");
      }).catch(function () { cmp.classList.remove("is-loading"); out.textContent = "Network problem. Please try again."; });
    });
  }
})();
