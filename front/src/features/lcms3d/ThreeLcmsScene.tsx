import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Lcms3DMap } from "./types";

interface Props {
  data: Lcms3DMap;
  height?: number;
}

const X_SIZE = 12;
const Y_SIZE = 5.6;
const Z_SIZE = 8;
const AXIS_ORIGIN = new THREE.Vector3(-X_SIZE / 2, 0, -Z_SIZE / 2);
const AXIS_COLORS = {
  rt: 0x2563eb,
  intensity: 0xdc2626,
  mz: 0x16a34a,
  grid: 0xcbd5e1,
  frame: 0x64748b,
  text: "#1e293b",
};

export function ThreeLcmsScene({ data, height = 420 }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf8fafc);

    const camera = new THREE.PerspectiveCamera(44, 1, 0.1, 1000);
    camera.position.set(9.5, 7.2, 10.5);

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
    controls.minDistance = 5;
    controls.maxDistance = 38;
    controls.target.set(0, 1.8, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 1));
    scene.add(makeCoordinateSystem(data));
    scene.add(makePointCloud(data));
    const anchors = makeAnchors(data);
    if (anchors) scene.add(anchors);

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
  }, [data]);

  return (
    <div
      ref={containerRef}
      className="relative w-full overflow-hidden rounded-md border border-border bg-background"
      style={{ height }}
    >
      <div className="pointer-events-none absolute left-3 top-3 z-10 rounded bg-background/80 px-2 py-1 text-[11px] font-medium text-muted-foreground shadow-sm ring-1 ring-border">
        <div className="flex gap-3">
          <span className="text-blue-700">X: RT (s)</span>
          <span className="text-green-700">Z: m/z</span>
          <span className="text-red-700">Y: intensity</span>
          <span>O: origin</span>
        </div>
      </div>
    </div>
  );
}

function makePointCloud(data: Lcms3DMap): THREE.Points {
  const rt = data.points.rt ?? [];
  const mz = data.points.mz ?? [];
  const intensity = data.points.intensity ?? [];
  const n = Math.min(rt.length, mz.length, intensity.length);
  const positions = new Float32Array(n * 3);
  const colors = new Float32Array(n * 3);

  const rtMin = finiteOr(data.axes.x.min, Math.min(...rt));
  const rtMax = finiteOr(data.axes.x.max, Math.max(...rt));
  const mzMin = finiteOr(data.axes.y.min, Math.min(...mz));
  const mzMax = finiteOr(data.axes.y.max, Math.max(...mz));
  const visualIntMin = finiteOr(Math.min(...intensity.filter(Number.isFinite)), data.axes.z.min);
  const intMax = finiteOr(data.axes.z.max, Math.max(...intensity));
  const heightLogMin = 0;
  const heightLogMax = Math.log10(Math.max(0, intMax) + 1);
  const colorLogMin = Math.log10(Math.max(0, visualIntMin) + 1);
  const colorLogMax = Math.log10(Math.max(0, intMax) + 1);

  for (let i = 0; i < n; i++) {
    const x = scale(rt[i], rtMin, rtMax, -X_SIZE / 2, X_SIZE / 2);
    const z = scale(mz[i], mzMin, mzMax, -Z_SIZE / 2, Z_SIZE / 2);
    const logIntensity = Math.log10(Math.max(0, intensity[i]) + 1);
    const yNorm = scale(logIntensity, heightLogMin, heightLogMax, 0, 1);
    const colorNorm = scale(logIntensity, colorLogMin, colorLogMax, 0, 1);
    const y = Math.max(0, Math.min(1, yNorm)) * Y_SIZE;

    positions[i * 3] = x;
    positions[i * 3 + 1] = y;
    positions[i * 3 + 2] = z;

    const color = colorForIntensity(colorNorm);
    colors[i * 3] = color.r;
    colors[i * 3 + 1] = color.g;
    colors[i * 3 + 2] = color.b;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  geometry.computeBoundingSphere();

  const material = new THREE.PointsMaterial({
    size: 3,
    sizeAttenuation: false,
    vertexColors: true,
    transparent: true,
    opacity: 0.9,
    depthWrite: false,
  });

  return new THREE.Points(geometry, material);
}

function makeCoordinateSystem(data: Lcms3DMap): THREE.Group {
  const group = new THREE.Group();
  group.add(makeGrid());
  group.add(makeBoundingBox());
  group.add(makeAxisArrow(new THREE.Vector3(X_SIZE, 0, 0), AXIS_COLORS.rt, 0.045));
  group.add(makeAxisArrow(new THREE.Vector3(0, Y_SIZE, 0), AXIS_COLORS.intensity, 0.045));
  group.add(makeAxisArrow(new THREE.Vector3(0, 0, Z_SIZE), AXIS_COLORS.mz, 0.045));
  group.add(makeAxisTicks(data));
  group.add(makeOriginMarker());

  group.add(makeTextSprite("O", AXIS_COLORS.text, 0.42, 0.24, AXIS_ORIGIN.clone().add(new THREE.Vector3(-0.32, -0.02, -0.32))));
  group.add(makeTextSprite("X: RT (s)", "#1d4ed8", 1.16, 0.32, AXIS_ORIGIN.clone().add(new THREE.Vector3(X_SIZE + 0.82, 0, 0))));
  group.add(makeTextSprite("Y: Intensity", "#b91c1c", 1.36, 0.32, AXIS_ORIGIN.clone().add(new THREE.Vector3(0, Y_SIZE + 0.64, 0))));
  group.add(makeTextSprite("Z: m/z", "#15803d", 0.9, 0.32, AXIS_ORIGIN.clone().add(new THREE.Vector3(0, 0, Z_SIZE + 0.72))));
  return group;
}

function makeGrid(): THREE.LineSegments {
  const x0 = -X_SIZE / 2;
  const x1 = X_SIZE / 2;
  const z0 = -Z_SIZE / 2;
  const z1 = Z_SIZE / 2;
  const vertices: number[] = [];
  for (let i = 0; i <= 12; i++) {
    const x = x0 + (X_SIZE * i) / 12;
    vertices.push(x, 0, z0, x, 0, z1);
  }
  for (let i = 0; i <= 10; i++) {
    const z = z0 + (Z_SIZE * i) / 10;
    vertices.push(x0, 0, z, x1, 0, z);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
  return new THREE.LineSegments(
    geometry,
    new THREE.LineBasicMaterial({ color: AXIS_COLORS.grid, transparent: true, opacity: 0.72 }),
  );
}

function makeBoundingBox(): THREE.Group {
  const group = new THREE.Group();
  const x0 = -X_SIZE / 2;
  const x1 = X_SIZE / 2;
  const z0 = -Z_SIZE / 2;
  const z1 = Z_SIZE / 2;
  const y0 = 0;
  const y1 = Y_SIZE;
  const edges: Array<[number, number, number, number, number, number]> = [
    [x0, y0, z0, x1, y0, z0],
    [x1, y0, z0, x1, y0, z1],
    [x1, y0, z1, x0, y0, z1],
    [x0, y0, z1, x0, y0, z0],
    [x0, y1, z0, x1, y1, z0],
    [x1, y1, z0, x1, y1, z1],
    [x1, y1, z1, x0, y1, z1],
    [x0, y1, z1, x0, y1, z0],
    [x0, y0, z0, x0, y1, z0],
    [x1, y0, z0, x1, y1, z0],
    [x1, y0, z1, x1, y1, z1],
    [x0, y0, z1, x0, y1, z1],
  ];
  const material = new THREE.MeshBasicMaterial({ color: AXIS_COLORS.frame, transparent: true, opacity: 0.58 });
  for (const edge of edges) {
    group.add(makeCylinderBetween(new THREE.Vector3(edge[0], edge[1], edge[2]), new THREE.Vector3(edge[3], edge[4], edge[5]), 0.012, material));
  }
  return group;
}

function makeAxisArrow(direction: THREE.Vector3, color: number, radius: number): THREE.Group {
  const group = new THREE.Group();
  const length = direction.length();
  const unit = direction.clone().normalize();
  const shaftLength = Math.max(0.1, length - 0.34);
  const shaftEnd = AXIS_ORIGIN.clone().add(unit.clone().multiplyScalar(shaftLength));

  const material = new THREE.MeshBasicMaterial({ color });
  group.add(makeCylinderBetween(AXIS_ORIGIN, shaftEnd, radius, material));

  const cone = new THREE.ConeGeometry(0.14, 0.38, 24);
  const arrow = new THREE.Mesh(cone, material);
  arrow.position.copy(AXIS_ORIGIN.clone().add(direction));
  arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), unit);
  group.add(arrow);
  return group;
}

function makeCylinderBetween(
  start: THREE.Vector3,
  end: THREE.Vector3,
  radius: number,
  material: THREE.Material,
): THREE.Mesh {
  const delta = end.clone().sub(start);
  const length = delta.length();
  const geometry = new THREE.CylinderGeometry(radius, radius, length, 12);
  const cylinder = new THREE.Mesh(geometry, material);
  cylinder.position.copy(start.clone().add(end).multiplyScalar(0.5));
  cylinder.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize());
  return cylinder;
}

function makeAxisTicks(data: Lcms3DMap): THREE.Group {
  const group = new THREE.Group();
  const tickMaterialRt = new THREE.LineBasicMaterial({ color: AXIS_COLORS.rt, transparent: true, opacity: 0.9 });
  const tickMaterialMz = new THREE.LineBasicMaterial({ color: AXIS_COLORS.mz, transparent: true, opacity: 0.9 });
  const tickMaterialIntensity = new THREE.LineBasicMaterial({ color: AXIS_COLORS.intensity, transparent: true, opacity: 0.9 });

  const rtTicks = makeTickValues(data.axes.x.min, data.axes.x.max, 4);
  for (const tick of rtTicks) {
    const x = scale(tick, data.axes.x.min, data.axes.x.max, -X_SIZE / 2, X_SIZE / 2);
    group.add(makeTickLine([x, 0, -Z_SIZE / 2, x, 0, -Z_SIZE / 2 - 0.18], tickMaterialRt));
    group.add(
      makeTextSprite(
        formatTick(tick),
        "#1d4ed8",
        0.74,
        0.24,
        new THREE.Vector3(x, -0.08, -Z_SIZE / 2 - 0.42),
      ),
    );
  }

  const mzTicks = makeTickValues(data.axes.y.min, data.axes.y.max, 4);
  for (const tick of mzTicks) {
    const z = scale(tick, data.axes.y.min, data.axes.y.max, -Z_SIZE / 2, Z_SIZE / 2);
    group.add(makeTickLine([-X_SIZE / 2, 0, z, -X_SIZE / 2 - 0.18, 0, z], tickMaterialMz));
    group.add(
      makeTextSprite(
        formatTick(tick),
        "#15803d",
        0.76,
        0.24,
        new THREE.Vector3(-X_SIZE / 2 - 0.46, -0.08, z),
      ),
    );
  }

  const intensityTicks = makeTickValues(0, data.axes.z.max, 4);
  const logMin = 0;
  const logMax = Math.log10(Math.max(0, data.axes.z.max) + 1);
  for (const tick of intensityTicks) {
    const y = scale(Math.log10(Math.max(0, tick) + 1), logMin, logMax, 0, Y_SIZE);
    group.add(makeTickLine([-X_SIZE / 2, y, -Z_SIZE / 2, -X_SIZE / 2 - 0.18, y, -Z_SIZE / 2], tickMaterialIntensity));
    group.add(
      makeTextSprite(
        formatTick(tick),
        "#b91c1c",
        0.84,
        0.24,
        new THREE.Vector3(-X_SIZE / 2 - 0.56, y, -Z_SIZE / 2 - 0.16),
      ),
    );
  }
  return group;
}

function makeTickLine(points: number[], material: THREE.LineBasicMaterial): THREE.Line {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
  return new THREE.Line(geometry, material);
}

function makeOriginMarker(): THREE.Mesh {
  const geometry = new THREE.SphereGeometry(0.08, 18, 12);
  const material = new THREE.MeshBasicMaterial({ color: 0x0f172a });
  const marker = new THREE.Mesh(geometry, material);
  marker.position.copy(AXIS_ORIGIN);
  return marker;
}

function makeTextSprite(
  text: string,
  color: string,
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
    ctx.strokeStyle = "rgba(248, 250, 252, 0.95)";
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

function makeAnchors(data: Lcms3DMap): THREE.LineSegments | null {
  const vertices: number[] = [];
  const rt = data.points.rt ?? [];
  const mz = data.points.mz ?? [];
  const scans = data.points.scan ?? [];

  const rtMin = finiteOr(data.axes.x.min, Math.min(...rt));
  const rtMax = finiteOr(data.axes.x.max, Math.max(...rt));
  const mzMin = finiteOr(data.axes.y.min, Math.min(...mz));
  const mzMax = finiteOr(data.axes.y.max, Math.max(...mz));

  const centerScan = data.anchors.centerScan;
  if (centerScan != null && scans.length > 0) {
    const idx = scans.findIndex((s) => Number(s) === Number(centerScan));
    if (idx >= 0 && Number.isFinite(rt[idx])) {
      const x = scale(rt[idx], rtMin, rtMax, -X_SIZE / 2, X_SIZE / 2);
      vertices.push(x, 0, -Z_SIZE / 2, x, Y_SIZE, -Z_SIZE / 2);
      vertices.push(x, 0, Z_SIZE / 2, x, Y_SIZE, Z_SIZE / 2);
    }
  }

  const precursorMz = data.anchors.precursorMz;
  if (precursorMz != null && precursorMz >= mzMin && precursorMz <= mzMax) {
    const z = scale(precursorMz, mzMin, mzMax, -Z_SIZE / 2, Z_SIZE / 2);
    vertices.push(-X_SIZE / 2, 0, z, X_SIZE / 2, 0, z);
    vertices.push(-X_SIZE / 2, Y_SIZE, z, X_SIZE / 2, Y_SIZE, z);
  }

  if (vertices.length === 0) return null;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
  return new THREE.LineSegments(
    geometry,
    new THREE.LineBasicMaterial({ color: 0xe11d48, transparent: true, opacity: 0.72 }),
  );
}

function colorForIntensity(t: number): THREE.Color {
  const stops = [
    new THREE.Color(0x2563eb),
    new THREE.Color(0x0891b2),
    new THREE.Color(0x16a34a),
    new THREE.Color(0xf59e0b),
    new THREE.Color(0xe11d48),
  ];
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
  if (abs >= 100_000) return value.toExponential(1);
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

function finiteOr(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
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
