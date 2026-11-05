import { useEffect, useRef, useState } from "preact/hooks";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { html } from "../html.js";
import { Ico } from "../icons.js";
import { prefersReducedMotion } from "../store.js";

const PART_COLOR = 0x54718f;
const EDGE_COLOR = 0x9bb7d2;
const HOLE_COLOR = 0x8eb1df;
const FLAG_COLOR = 0xdf9299;
const MAX_DIM_FALLBACK = 120;

function makeLabel(text, color) {
  const pad = 16;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  ctx.font = "600 44px Consolas, monospace";
  canvas.width = ctx.measureText(text).width + pad * 2;
  canvas.height = 72;
  const c2 = canvas.getContext("2d");
  c2.font = "600 44px Consolas, monospace";
  c2.fillStyle = "rgba(13,20,28,0.94)";
  c2.fillRect(0, 0, canvas.width, canvas.height);
  c2.strokeStyle = color;
  c2.lineWidth = 3;
  c2.strokeRect(1.5, 1.5, canvas.width - 3, canvas.height - 3);
  c2.fillStyle = color;
  c2.textBaseline = "middle";
  c2.fillText(text, pad, canvas.height / 2);

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  const scale = 0.09;
  sprite.scale.set(canvas.width * scale, canvas.height * scale, 1);
  return sprite;
}

/** 递归释放几何/材质/贴图，避免 WebGL 资源泄漏。 */
function disposeObject(obj) {
  if (!obj) return;
  obj.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    const mats = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
    mats.forEach((m) => {
      if (m.map) m.map.dispose();
      m.dispose();
    });
  });
}

export function ViewerPanel({ geometry, highlight }) {
  const hostRef = useRef(null);
  const ctxRef = useRef(null);

  const [autoRotate, setAutoRotate] = useState(false);
  const [wire, setWire] = useState(false);
  const [dims, setDims] = useState(true);

  // ---------------------------------------------------------------- 初始化（仅一次）
  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;

    const w0 = el.clientWidth || 560;
    const h0 = el.clientHeight || 380;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w0, h0);
    renderer.setClearAlpha(0);
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, w0 / h0, 0.1, 8000);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x253141, 1.15));
    const key = new THREE.DirectionalLight(0xffffff, 1.7);
    key.position.set(160, -220, 260);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x8eb1df, 0.7);
    rim.position.set(-240, 140, -180);
    scene.add(rim);

    const grid = new THREE.GridHelper(230, 24, 0x526174, 0x25303c);
    grid.material.transparent = true;
    grid.material.opacity = 0.42;
    scene.add(grid);

    const axes = new THREE.AxesHelper(26);
    axes.material.transparent = true;
    axes.material.opacity = 0.6;
    scene.add(axes);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.rotateSpeed = 0.7;
    controls.minDistance = MAX_DIM_FALLBACK * 0.6;
    controls.maxDistance = MAX_DIM_FALLBACK * 4;
    controls.autoRotateSpeed = 1.1;
    controls.target.set(0, 0, 0);

    camera.position.set(126, 138, 138);
    camera.lookAt(0, 0, 0);
    controls.update();

    /** @type {{renderer:any,scene:any,camera:any,controls:any,grid:any,axes:any,ModelGroup:any,plateMat:any,dimObjs:any[],holeMats:Record<string,any>,flagged:any[],maxDim:number}} */
    const ctx = {
      renderer, scene, camera, controls, grid, axes,
      modelGroup: null, plateMat: null, dimObjs: [], holeMats: {}, flagged: [],
      maxDim: MAX_DIM_FALLBACK,
    };
    ctxRef.current = ctx;

    const reduced = prefersReducedMotion();
    const clock = new THREE.Clock();
    let raf = 0;
    const animate = () => {
      raf = requestAnimationFrame(animate);
      if (!reduced && ctx.flagged.length) {
        const t = clock.getElapsedTime();
        const pulse = 1 + 0.06 * Math.sin(t * 3.4);
        ctx.flagged.forEach((m) => m.scale.set(pulse, 1, pulse));
      }
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    // resize 使用容器的**实时**尺寸（窗口缩放时高度会变）
    const resize = () => {
      const w = el.clientWidth || w0;
      const h = el.clientHeight || h0;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    window.addEventListener("resize", resize);
    let ro = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(resize);
      ro.observe(el);
    }

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      if (ro) ro.disconnect();
      disposeObject(ctx.modelGroup);
      disposeObject(grid);
      disposeObject(axes);
      controls.dispose();
      renderer.dispose();
      if (renderer.forceContextLoss) renderer.forceContextLoss();
      if (renderer.domElement.parentElement === el) el.removeChild(renderer.domElement);
      ctxRef.current = null;
    };
  }, []);

  // ---------------------------------------------------------------- 几何重建
  useEffect(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;

    if (ctx.modelGroup) {
      ctx.scene.remove(ctx.modelGroup);
      disposeObject(ctx.modelGroup);
    }
    ctx.holeMats = {};
    ctx.flagged = [];
    ctx.dimObjs = [];

    const group = new THREE.Group();
    ctx.modelGroup = group;
    ctx.scene.add(group);

    const bbox = geometry ? geometry.bbox : { length: MAX_DIM_FALLBACK, width: 80, height: 6 };
    const L = bbox.length;
    const W = bbox.width;
    const H = bbox.height;
    const maxDim = Math.max(L, W);
    ctx.maxDim = maxDim;

    const plateMat = new THREE.MeshStandardMaterial({
      color: PART_COLOR, metalness: 0.42, roughness: 0.34,
      transparent: true, opacity: 0.94, wireframe: false,
    });
    ctx.plateMat = plateMat;
    group.add(new THREE.Mesh(new THREE.BoxGeometry(L, W, H), plateMat));

    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(L, W, H)),
      new THREE.LineBasicMaterial({ color: EDGE_COLOR, transparent: true, opacity: 0.55 })
    );
    edges.name = "plate-edges";
    group.add(edges);

    (geometry ? geometry.holes : []).forEach((hole) => {
      const mat = new THREE.MeshStandardMaterial({
        color: HOLE_COLOR,
        emissive: new THREE.Color(HOLE_COLOR),
        emissiveIntensity: 0.12,
        transparent: true, opacity: 0.7, roughness: 0.3,
      });
      const cyl = new THREE.Mesh(
        new THREE.CylinderGeometry(hole.d / 2, hole.d / 2, H * 1.8, 30), mat
      );
      cyl.rotation.x = Math.PI / 2;                 // 轴沿厚度方向
      cyl.position.set(hole.x - L / 2, hole.y - W / 2, 0);
      cyl.name = hole.id;
      group.add(cyl);
      ctx.holeMats[hole.id] = mat;
    });

    group.rotation.x = -Math.PI / 2;                 // 立起为平板姿态（厚度沿 Y）

    ctx.grid.position.y = -H / 2 - 0.6;
    ctx.axes.position.set(-L / 2 - 6, -H / 2, W / 2 + 6);
    ctx.grid.scale.setScalar(maxDim / MAX_DIM_FALLBACK);
    ctx.axes.scale.setScalar(Math.max(0.4, maxDim / MAX_DIM_FALLBACK));

    // 等距尺寸标注
    const dimMat = new THREE.LineBasicMaterial({ color: 0xd6ae67, transparent: true, opacity: 0.75 });
    const off = H / 2 + 5;
    const lenLine = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-L / 2, -W / 2 - 6, off), new THREE.Vector3(L / 2, -W / 2 - 6, off),
    ]);
    const widLine = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-L / 2 - 6, -W / 2, off), new THREE.Vector3(-L / 2 - 6, W / 2, off),
    ]);
    const lLabel = makeLabel(String(L), "#d6ae67");
    lLabel.position.set(0, -W / 2 - 10, off);
    const wLabel = makeLabel(String(W), "#d6ae67");
    wLabel.position.set(-L / 2 - 12, 0, off);
    ctx.dimObjs = [new THREE.Line(lenLine, dimMat), new THREE.Line(widLine, dimMat), lLabel, wLabel];
    ctx.dimObjs.forEach((o) => group.add(o));

    // 保持相机距离随模型尺度自适应
    const camera = ctx.camera;
    const dist = Math.hypot(camera.position.x, camera.position.y, camera.position.z) || maxDim;
    const k = (maxDim * 1.2) / dist;
    camera.position.multiplyScalar(k);
    ctx.controls.minDistance = maxDim * 0.6;
    ctx.controls.maxDistance = maxDim * 4;
    ctx.controls.update();
  }, [geometry]);

  // ---------------------------------------------------------------- 开关：只改属性，不重建场景
  useEffect(() => {
    const ctx = ctxRef.current;
    if (ctx && ctx.plateMat) ctx.plateMat.wireframe = wire;
  }, [wire]);

  useEffect(() => {
    const ctx = ctxRef.current;
    if (ctx) ctx.dimObjs.forEach((o) => { o.visible = dims; });
  }, [dims]);

  useEffect(() => {
    const ctx = ctxRef.current;
    if (ctx) ctx.controls.autoRotate = autoRotate;
  }, [autoRotate]);

  // ---------------------------------------------------------------- 高亮：只改材质
  useEffect(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    const flags = highlight || [];
    ctx.flagged = [];
    Object.entries(ctx.holeMats).forEach(([id, mat]) => {
      const on = flags.includes(id);
      mat.color.set(on ? FLAG_COLOR : HOLE_COLOR);
      mat.emissive.set(on ? FLAG_COLOR : HOLE_COLOR);
      mat.emissiveIntensity = on ? 0.5 : 0.12;
      mat.opacity = on ? 0.98 : 0.7;
    });
    ctx.modelGroup &&
      ctx.modelGroup.traverse((o) => {
        if (flags.includes(o.name)) ctx.flagged.push(o);
      });
  }, [highlight, geometry]);

  const resetView = () => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    const d = ctx.maxDim || MAX_DIM_FALLBACK;
    ctx.camera.position.set(d * 1.05, d * 1.15, d * 1.15);
    ctx.controls.target.set(0, 0, 0);
    ctx.controls.update();
  };

  return html`
    <div class="viewer-wrap">
      <div
        class="viewer"
        ref=${hostRef}
        role="img"
        aria-label=${geometry
          ? `三维模型：${geometry.bbox.length}×${geometry.bbox.width}×${geometry.bbox.height}，${geometry.hole_count} 个孔`
          : "三维模型预览"}
      ></div>

      ${!geometry
        ? html`<div class="viewer-empty">
            <${Ico} name="cube" size=${26} />
            <div>解析图纸后在此生成参数化模型</div>
          </div>`
        : null}

      ${geometry
        ? html`<div class="viewer-badge">
            <span class="badge mono">${geometry.bbox.length}×${geometry.bbox.width}×${geometry.bbox.height}</span>
            <span class="badge">孔 ${geometry.hole_count}</span>
          </div>`
        : null}

      <div class="viewer-tools">
        <button class=${`icon-btn ${autoRotate ? "is-on" : ""}`} title="自动旋转" aria-label="自动旋转"
          aria-pressed=${autoRotate} onClick=${() => setAutoRotate((v) => !v)}>
          <${Ico} name="rotate" size=${15} />
        </button>
        <button class=${`icon-btn ${wire ? "is-on" : ""}`} title="线框" aria-label="线框模式"
          aria-pressed=${wire} onClick=${() => setWire((v) => !v)}>
          <${Ico} name="grid" size=${15} />
        </button>
        <button class=${`icon-btn ${dims ? "is-on" : ""}`} title="尺寸标注" aria-label="尺寸标注"
          aria-pressed=${dims} onClick=${() => setDims((v) => !v)}>
          <${Ico} name="target" size=${15} />
        </button>
        <button class="icon-btn" title="重置视角" aria-label="重置视角" onClick=${resetView}>
          <${Ico} name="rotate" size=${15} />
        </button>
      </div>
    </div>
  `;
}