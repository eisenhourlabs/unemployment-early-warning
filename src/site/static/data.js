/* Data & Downloads page: filter the table by search text, page, source, frequency, and state series. */
(function () {
  "use strict";
  var form = document.getElementById("filters");
  if (!form) return;
  var rows = Array.prototype.slice.call(document.querySelectorAll("table.files tbody tr"));
  var count = document.getElementById("row-count");

  function apply() {
    var q = form.elements.q.value.trim().toLowerCase();
    var page = form.elements.page.value, source = form.elements.source.value, freq = form.elements.frequency.value;
    var states = form.elements.states.checked, shown = 0;
    rows.forEach(function (tr) {
      var d = tr.dataset;
      var ok = (!q || d.search.indexOf(q) >= 0) && (!page || d.page === page) && (!source || d.source === source) &&
               (!freq || d.frequency === freq) && (states || !d.state);
      tr.hidden = !ok;
      if (ok) shown++;
    });
    count.textContent = "Showing " + shown + " file" + (shown === 1 ? "" : "s") + (states ? "" : " (state series hidden)");
  }
  form.addEventListener("input", apply);
  form.addEventListener("change", apply);
  form.addEventListener("submit", function (e) { e.preventDefault(); });
  apply();
})();
