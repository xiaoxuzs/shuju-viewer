/*  mzml-demo / static frontend
 *  纯原生 JS + Plotly.js。没有构建步骤。
 */

const $ = (id) => document.getElementById(id);

async function refreshStatus() {
  try {
    const r = await fetch("/api/mzml/status");
    const s = await r.json();
    $("status").textContent = `mzML: ${(s.path || "(none)").split(/[\\/]/).pop()} | MS1=${s.ms1_count} MS2=${s.ms2_count}`;
  } catch (e) {
    $("status").textContent = "(status error)";
  }
}

async function refreshList() {
  const r = await fetch("/api/prsm/list");
  const files = await r.json();
  const sel = $("prsm-select");
  sel.innerHTML = "";
  for (const f of files) {
    const opt = document.createElement("option");
    opt.value = f;
    opt.textContent = f;
    sel.appendChild(opt);
  }
  return files;
}

function fmtSummary(s) {
  const acc = s.sequence_name || "-";
  const desc = s.sequence_description || "";
  return `
    <div><b>Protein</b> ${acc}</div>
    <div style="color:#666;font-size:12px;margin-bottom:6px;">${desc}</div>
    <div class="row">
      <div><b>PrSM ID</b> ${s.prsm_id}</div>
      <div><b>E-value</b> ${s.e_value}</div>
      <div><b>P-value</b> ${s.p_value}</div>
    </div>
    <div class="row">
      <div><b>Precursor mass</b> ${s.precursor_mass} Da</div>
      <div><b>Charge</b> ${s.precursor_charge}+</div>
      <div><b>Precursor m/z</b> ${s.precursor_mz}</div>
    </div>
    <div class="row">
      <div><b>MS1 scan</b> ${s.ms1_scan ?? "-"}</div>
      <div><b>MS2 scan</b> ${s.ms2_scan ?? "-"}</div>
      <div><b>Matched fragments</b> ${s.matched_fragment_number}</div>
    </div>
  `;
}

function renderSeq(a) {
  const box = $("seq");
  box.innerHTML = "";
  const residues = a.residue || [];
  const cleavage = a.cleavage || [];
  const clv = Object.create(null);
  for (const c of cleavage) clv[+c.position] = c;

  // Cleavage position 0 = before residue 0  (no bar shown)
  // For each residue i, render the cleavage bar BEFORE it (position = i).
  for (let i = 0; i < residues.length; i++) {
    const cp = clv[i];
    if (cp) {
      const hasN = cp.exist_n_ion === "1";
      const hasC = cp.exist_c_ion === "1";
      if (hasN || hasC) {
        const bar = document.createElement("span");
        bar.className =
          "seq-bar " + (hasN && hasC ? "both" : hasN ? "n" : "c");
        bar.textContent = "|";
        bar.title =
          (hasN ? "N-term (B) ion " : "") +
          (hasC ? (hasN ? "+ " : "") + "C-term (Y) ion " : "") +
          "matched at cleavage " + i;
        box.appendChild(bar);
      }
    }
    const span = document.createElement("span");
    span.className = "seq-res";
    const before = clv[i];
    const after = clv[i + 1];
    const hasN = after && after.exist_n_ion === "1";
    const hasC = before && before.exist_c_ion === "1";
    if (hasN && hasC) span.classList.add("both");
    else if (hasN) span.classList.add("n");
    else if (hasC) span.classList.add("c");
    span.textContent = residues[i].acid;
    box.appendChild(span);
  }

  const ms = a.mass_shift;
  const mbox = $("massshift");
  mbox.innerHTML = ms
    ? `<b>Mass shift</b> : positions ${ms.left_position}–${ms.right_position}, ${ms.anno} Da (${ms.shift_type})`
    : "";
}

function stemsFromPeaks(mz, intensity) {
  const xs = [], ys = [];
  for (let i = 0; i < mz.length; i++) {
    xs.push(mz[i], mz[i], null);
    ys.push(0, intensity[i], null);
  }
  return [xs, ys];
}

function renderMs1(ms1) {
  const msg = $("ms1-msg");
  msg.textContent = "";
  if (ms1.not_found) {
    msg.textContent = `MS1 scan ${ms1.scan ?? "?"} not found in mzML.`;
  }

  const traces = [];
  if (ms1.mz && ms1.mz.length) {
    const [xs, ys] = stemsFromPeaks(ms1.mz, ms1.intensity);
    traces.push({
      x: xs, y: ys, mode: "lines", name: "MS1 peaks",
      line: { color: "#888", width: 1 }, hoverinfo: "x+y",
    });
  }

  const layout = {
    margin: { t: 20, l: 70, r: 20, b: 40 },
    xaxis: { title: "m/z" },
    yaxis: { title: "Intensity" },
    showlegend: false,
  };

  // precursor window shading
  if (ms1.precursor && ms1.precursor.target_mz) {
    const p = ms1.precursor;
    const low = p.target_mz - (p.lower_offset || 0);
    const high = p.target_mz + (p.upper_offset || 0);
    layout.shapes = [{
      type: "rect", xref: "x", yref: "paper",
      x0: low, x1: high, y0: 0, y1: 1,
      fillcolor: "rgba(255,180,60,0.18)", line: { width: 0 },
    }];
    layout.annotations = [{
      x: p.target_mz, y: 1, xref: "x", yref: "paper",
      text: `precursor m/z ${p.target_mz.toFixed(4)}${p.charge ? ` (z=${p.charge})` : ""}`,
      showarrow: false, yanchor: "bottom", yshift: 2,
      font: { color: "#c77", size: 12 },
    }];
    // zoom to window ± some breathing room
    layout.xaxis.range = [low - 3, high + 3];
  }

  Plotly.newPlot("ms1-chart", traces, layout, { responsive: true, displaylogo: false });
}

function renderMs2(ms2) {
  const traces = [];

  if (ms2.mz && ms2.mz.length) {
    const [xs, ys] = stemsFromPeaks(ms2.mz, ms2.intensity);
    traces.push({
      x: xs, y: ys, mode: "lines", name: "raw peaks",
      line: { color: "#c0c0c0", width: 1 }, hoverinfo: "x+y",
    });
  }

  const matched = ms2.matched_peaks || [];
  if (matched.length) {
    const mxs = [], mys = [];
    for (const p of matched) {
      mxs.push(p.monoisotopic_mz, p.monoisotopic_mz, null);
      mys.push(0, p.intensity, null);
    }
    traces.push({
      x: mxs, y: mys, mode: "lines", name: "matched ions",
      line: { color: "crimson", width: 2 }, hoverinfo: "skip",
    });
    traces.push({
      x: matched.map((p) => p.monoisotopic_mz),
      y: matched.map((p) => p.intensity),
      mode: "markers+text",
      marker: { color: "crimson", size: 6 },
      text: matched.map((p) => `${p.ion_type}${p.ion_position}`),
      textposition: "top center",
      textfont: { color: "crimson", size: 11 },
      hovertext: matched.map(
        (p) =>
          `${p.ion_type}${p.ion_position}<br>` +
          `mono mass = ${p.monoisotopic_mass.toFixed(4)} Da<br>` +
          `m/z = ${p.monoisotopic_mz.toFixed(4)}<br>` +
          `z = ${p.charge}+<br>` +
          `theoretical = ${p.theoretical_mass.toFixed(4)}<br>` +
          `ppm = ${p.ppm.toFixed(2)}`
      ),
      hoverinfo: "text",
      name: "ion labels",
    });
  }

  Plotly.newPlot(
    "ms2-chart",
    traces,
    {
      margin: { t: 20, l: 70, r: 20, b: 40 },
      xaxis: { title: "m/z" },
      yaxis: { title: "Intensity" },
      showlegend: true,
      legend: { orientation: "h", y: 1.1 },
    },
    { responsive: true, displaylogo: false }
  );
}

async function loadView() {
  const file = $("prsm-select").value;
  if (!file) return;
  const r = await fetch(`/api/prsm/view?file=${encodeURIComponent(file)}`);
  if (!r.ok) {
    $("summary").innerHTML = `<span class="err">load failed: ${await r.text()}</span>`;
    return;
  }
  const data = await r.json();
  $("summary").innerHTML = fmtSummary(data.summary);
  renderSeq(data.annotation);
  renderMs1(data.ms1);
  renderMs2(data.ms2);
}

document.getElementById("reload").addEventListener("click", loadView);
document.getElementById("prsm-select").addEventListener("change", loadView);

(async () => {
  await refreshStatus();
  const files = await refreshList();
  if (files.length) await loadView();
  else
    $("summary").innerHTML =
      `<em>data/ 目录里还没有 prsm*.js 文件。先运行 <code>scripts/prsmup.py</code> 生成，然后刷新页面。</em>`;
})();
