/* Client-side search over the prebuilt /assets/search.json index.
   No network access beyond the same origin, no third-party code, no inline scripts
   (the page CSP forbids them, which is why this is a separate file). */

(function () {
  "use strict";

  var input = document.getElementById("q");
  var box = document.getElementById("results");
  var toggle = document.getElementById("navtoggle");
  var nav = document.getElementById("nav");
  if (!input || !box) return;

  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  var index = null;
  var loading = false;
  var sel = -1;
  var hits = [];

  function load(cb) {
    if (index) return cb();
    if (loading) return;
    loading = true;
    fetch("/assets/search.json")
      .then(function (r) { return r.json(); })
      .then(function (j) { index = j; loading = false; cb(); })
      .catch(function () { index = []; loading = false; cb(); });
  }

  function esc(s) {
    return s.replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function snippet(text, terms) {
    var low = text.toLowerCase();
    var at = -1;
    for (var i = 0; i < terms.length; i++) {
      var p = low.indexOf(terms[i]);
      if (p >= 0 && (at < 0 || p < at)) at = p;
    }
    if (at < 0) at = 0;
    var start = Math.max(0, at - 60);
    var out = (start > 0 ? "…" : "") + text.slice(start, start + 220).trim();
    // bold the matched terms without ever injecting markup
    var safe = esc(out);
    terms.forEach(function (t) {
      if (t.length < 2) return;
      safe = safe.replace(new RegExp("(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi"), "<mark>$1</mark>");
    });
    return safe;
  }

  function render(terms) {
    if (!terms.length) { box.hidden = true; box.innerHTML = ""; return; }
    if (!hits.length) {
      box.innerHTML = '<div class="empty">No matches.</div>';
      box.hidden = false;
      return;
    }
    box.innerHTML = hits
      .slice(0, 40)
      .map(function (h, i) {
        return (
          '<a class="result' + (i === sel ? " sel" : "") + '" href="' + h.u + '">' +
          "<b>" + esc(h.t) + "</b>" +
          "<span>" + esc(h.h) + "</span>" +
          "<em>" + snippet(h.x, terms) + "</em>" +
          "</a>"
        );
      })
      .join("");
    box.hidden = false;
  }

  function search() {
    var q = input.value.trim().toLowerCase();
    sel = -1;
    if (q.length < 2) { hits = []; render([]); return; }
    load(function () {
      var terms = q.split(/\s+/).filter(function (t) { return t.length > 1; });
      hits = [];
      for (var i = 0; i < index.length; i++) {
        var d = index[i];
        var hay = (d.h + " " + d.x + " " + d.t).toLowerCase();
        var ok = true;
        var score = 0;
        for (var j = 0; j < terms.length; j++) {
          if (hay.indexOf(terms[j]) < 0) { ok = false; break; }
          if (d.h.toLowerCase().indexOf(terms[j]) >= 0) score += 5;
          score += 1;
        }
        if (ok) { hits.push({ u: d.u, t: d.t, h: d.h, x: d.x, s: score }); }
      }
      hits.sort(function (a, b) { return b.s - a.s; });
      render(terms);
    });
  }

  var t = null;
  input.addEventListener("input", function () {
    clearTimeout(t);
    t = setTimeout(search, 90);
  });

  input.addEventListener("keydown", function (e) {
    if (box.hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel + 1, Math.min(hits.length, 40) - 1); render(input.value.trim().toLowerCase().split(/\s+/)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel - 1, 0); render(input.value.trim().toLowerCase().split(/\s+/)); }
    else if (e.key === "Enter") { if (hits[sel >= 0 ? sel : 0]) window.location.href = hits[sel >= 0 ? sel : 0].u; }
    else if (e.key === "Escape") { box.hidden = true; input.blur(); }
  });

  document.addEventListener("click", function (e) {
    if (!box.contains(e.target) && e.target !== input) box.hidden = true;
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && document.activeElement !== input) { e.preventDefault(); input.focus(); }
  });
})();
