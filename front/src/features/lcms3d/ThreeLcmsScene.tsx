import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { useTheme } from "@/features/theme/themeContext";
import type { Peak } from "./types";

interface Props {
  peaks: Peak[];
  height?: number;
}

const X_SIZE = 12;
const Z_SIZE = 8;

export function ThreeLcmsScene({ peaks, height = 480 }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const themeColors = readSceneTheme(container);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(themeColors.background);

    const camera = new THREE.PerspectiveCamera(44, 1, 0.1, 1000);
    camera.position.set(0.5, 6.5, 14);

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.domElement.className = "h-full w-full rounded-md";
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = true;
    controls.minDistance = 6;
    controls.maxDistance = 40;
    controls.target.set(0, 1.8, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 1));

    const mzRange = computeMzRange(peaks);
    const intensityMax = computeIntensityMax(peaks);
    scene.add(makeAxes(mzRange, intensityMax, themeColors));
    const sticks = makeStickPlot(peaks, mzRange, intensityMax, themeColors.heat);
    if (sticks) scene.add(sticks);

    const resize = () => {
      const w = Math.max(1, container.clientWidth);
      const h = Math.max(1, container.clientHeight);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    };
    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);

    let raf = 0;
    const render = () => {
      controls.update();
      renderer.render(scene, camera);
      raf = window.requestAnimationFrame(render);
    };
    render();

    return () => {
      window.cancelAnimationFrame(raf);
      resizeObserver.disconnect();
      controls.dispose();
      disposeObject(scene);
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [peaks, resolvedTheme]);

  return (
    <div
      ref={containerRef}
      className="relative w-full overflow-hidden rounded-md border border-border bg-background"
      style={{ height }}
    >
      <div className="pointer-events-none absolute left-3 top-3 z-10 rounded bg-background/85 px-2 py-1 text-[11px] font-medium text-muted-foreground shadow-sm ring-1 ring-border">
        <div className="flex gap-3">
          <span className="text-foreground">X: m/z</span>
          <span className="text-foreground">Y: Intensity</span>
          <span className="text-[hsl(var(--chart-series-5))]">Color: Intensity (Viridis)</span>
        </div>
      </div>
    </div>
  );
}

// ---- geometry / data ------------------------------------------------------

interface MzRange { min: number; max: number; }

interface SceneThemeColors {
  background: string;
  axis: string;
  grid: string;
  text: string;
  label: string;
  labelHalo: string;
  heat: string[];
}

function readSceneTheme(container: HTMLElement): SceneThemeColors {
  const read = (variable: string) => {
    const probe = document.createElement("span");
    probe.style.cssText = `position:absolute;opacity:0;pointer-events:none;color:hsl(var(${variable}))`;
    container.appendChild(probe);
    const color = getComputedStyle(probe).color;
    probe.remove();
    return color;
  };

  return {
    background: read("--chart-scene-background"),
    axis: read("--chart-axis"),
    grid: read("--chart-grid"),
    text: read("--chart-text"),
    label: read("--foreground"),
    labelHalo: read("--chart-label-halo"),
    heat: [1, 2, 3, 4, 5, 6].map((index) => read(`--chart-heat-${index}`)),
  };
}

function computeMzRange(peaks: Peak[]): MzRange {
  if (peaks.length === 0) return { min: 0, max: 1 };
  let min = Infinity, max = -Infinity;
  for (const p of peaks) {
    if (!Number.isFinite(p.mz)) continue;
    if (p.mz < min) min = p.mz;
    if (p.mz > max) max = p.mz;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
    return { min: min - 0.5, max: max + 0.5 };
  }
  return { min, max };
}

function computeIntensityMax(peaks: Peak[]): number {
  let max = 0;
  for (const p of peaks) {
    if (Number.isFinite(p.intensity) && p.intensity > max) max = p.intensity;
  }
  return max > 0 ? max : 1;
}

function makeStickPlot(
  peaks: Peak[],
  mz: MzRange,
  iMax: number,
  heatColors: string[],
): THREE.LineSegments | null {
  if (peaks.length === 0) return null;
  const positions = new Float32Array(peaks.length * 6);
  const colors = new Float32Array(peaks.length * 6);
  const Y_SIZE = 5.6;

  for (let i = 0; i < peaks.length; i++) {
    const p = peaks[i];
    const x = scale(p.mz, mz.min, mz.max, -X_SIZE / 2, X_SIZE / 2);
    const y = scale(Math.max(0, p.intensity), 0, iMax, 0, Y_SIZE);
    const t = iMax > 0 ? Math.max(0, Math.min(1, p.intensity / iMax)) : 0;
    const c = viridis(t, heatColors);

    const off = i * 6;
    positions[off    ] = x; positions[off + 1] = 0; positions[off + 2] = 0;
    positions[off + 3] = x; positions[off + 4] = y; positions[off + 5] = 0;

    colors[off    ] = c.r; colors[off + 1] = c.g; colors[off + 2] = c.b;
    colors[off + 3] = c.r; colors[off + 4] = c.g; colors[off + 5] = c.b;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

  const material = new THREE.LineBasicMaterial({
    vertexColors: true,
    transparent: false,
  });
  return new THREE.LineSegments(geometry, material);
}

function makeAxes(mz: MzRange, iMax: number, colors: SceneThemeColors): THREE.Group {
  const group = new THREE.Group();
  const Y_SIZE = 5.6;
  const x0 = -X_SIZE / 2, x1 = X_SIZE / 2;

  // ground grid (m/z direction only — Z 厚度 = 0)
  const gridV: number[] = [];
  for (let i = 0; i <= 12; i++) {
    const x = x0 + (X_SIZE * i) / 12;
    gridV.push(x, 0, -Z_SIZE / 2, x, 0, Z_SIZE / 2);
  }
  for (let i = 0; i <= 4; i++) {
    const z = -Z_SIZE / 2 + (Z_SIZE * i) / 4;
    gridV.push(x0, 0, z, x1, 0, z);
  }
  const gridGeo = new THREE.BufferGeometry();
  gridGeo.setAttribute("position", new THREE.Float32BufferAttribute(gridV, 3));
  group.add(new THREE.LineSegments(
    gridGeo,
    new THREE.LineBasicMaterial({ color: colors.grid, transparent: true, opacity: 0.55 }),
  ));

  // X axis (m/z) and Y axis (intensity) only
  const axisMat = new THREE.LineBasicMaterial({ color: colors.axis });
  const xAxis = new THREE.BufferGeometry();
  xAxis.setAttribute("position", new THREE.Float32BufferAttribute([x0, 0, 0, x1, 0, 0], 3));
  group.add(new THREE.Line(xAxis, axisMat));
  const yAxis = new THREE.BufferGeometry();
  yAxis.setAttribute("position", new THREE.Float32BufferAttribute([x0, 0, 0, x0, Y_SIZE, 0], 3));
  group.add(new THREE.Line(yAxis, axisMat));

  // ticks
  const mzTicks = makeTickValues(mz.min, mz.max, 5);
  for (const t of mzTicks) {
    const x = scale(t, mz.min, mz.max, x0, x1);
    group.add(makeTextSprite(formatTick(t), colors.text, colors.labelHalo, 0.78, 0.22, new THREE.Vector3(x, -0.12, 0)));
  }
  const intTicks = makeTickValues(0, iMax, 5);
  for (const t of intTicks) {
    const y = scale(t, 0, iMax, 0, Y_SIZE);
    group.add(makeTextSprite(formatTick(t), colors.text, colors.labelHalo, 0.96, 0.22, new THREE.Vector3(x0 - 0.7, y, 0)));
  }

  // axis labels
  group.add(makeTextSprite("m/z (Da)", colors.label, colors.labelHalo, 1.1, 0.28, new THREE.Vector3(x1 + 0.9, -0.16, 0)));
  group.add(makeTextSprite("Intensity", colors.label, colors.labelHalo, 0.78, 0.28, new THREE.Vector3(x0 - 0.7, Y_SIZE + 0.4, 0)));
  return group;
}

function makeTextSprite(
  text: string,
  color: string,
  haloColor: string,
  width: number,
  height: number,
  position: THREE.Vector3,
): THREE.Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 160;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.font = "600 52px Inter, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.lineWidth = 8;
    ctx.strokeStyle = haloColor;
    ctx.fillStyle = color;
    ctx.strokeText(text, canvas.width / 2, canvas.height / 2);
    ctx.fillText(text, canvas.width / 2, canvas.height / 2);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: false,
    depthWrite: false,
  });
  const sprite = new THREE.Sprite(material);
  sprite.position.copy(position);
  sprite.scale.set(width, height, 1);
  sprite.renderOrder = 10;
  return sprite;
}

// Viridis-approximate colormap (5-stop linear interpolation)
function viridis(t: number, colors: string[]): THREE.Color {
  const stops = colors.map((color) => new THREE.Color(color));
  const clamped = Math.max(0, Math.min(1, t));
  const scaled = clamped * (stops.length - 1);
  const idx = Math.min(stops.length - 2, Math.floor(scaled));
  return stops[idx].clone().lerp(stops[idx + 1], scaled - idx);
}

function makeTickValues(min: number, max: number, count: number): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || count <= 1) return [];
  if (min === max) return [min];
  const out: number[] = [];
  for (let i = 0; i < count; i++) {
    out.push(min + ((max - min) * i) / (count - 1));
  }
  return out;
}

function formatTick(value: number): string {
  if (!Number.isFinite(value)) return "";
  const abs = Math.abs(value);
  if (abs === 0) return "0";
  if (abs >= 1e5) return value.toExponential(1);
  if (abs >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (abs >= 100) return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  if (abs >= 10) return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function scale(value: number, d0: number, d1: number, r0: number, r1: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(d0) || !Number.isFinite(d1) || d0 === d1) {
    return (r0 + r1) / 2;
  }
  return r0 + ((value - d0) / (d1 - d0)) * (r1 - r0);
}

function disposeObject(object: THREE.Object3D) {
  object.traverse((child) => {
    const mesh = child as THREE.Object3D & {
      geometry?: THREE.BufferGeometry;
      material?: (THREE.Material & { map?: THREE.Texture }) | Array<THREE.Material & { map?: THREE.Texture }>;
    };
    mesh.geometry?.dispose();
    if (Array.isArray(mesh.material)) {
      mesh.material.forEach((m) => {
        m.map?.dispose();
        m.dispose();
      });
    } else {
      mesh.material?.map?.dispose();
      mesh.material?.dispose();
    }
  });
}
