/* Arc-reactor orb: WebGL plasma with a graceful 2D canvas fallback. */
(function () {
  const VS = `
    attribute vec2 p;
    varying vec2 uv;
    void main(){ uv = p * 0.5 + 0.5; gl_Position = vec4(p, 0.0, 1.0); }
  `;

  const FS = `
    precision highp float;
    varying vec2 uv;
    uniform vec2 u_res;
    uniform float u_time;
    uniform float u_amp;
    uniform float u_warm;
    uniform vec3 u_accent;

    float hash(vec2 p){
      p = fract(p * vec2(123.34, 456.21));
      p += dot(p, p + 45.32);
      return fract(p.x * p.y);
    }
    float noise(vec2 p){
      vec2 i = floor(p), f = fract(p);
      f = f * f * (3.0 - 2.0 * f);
      float a = hash(i), b = hash(i + vec2(1.0, 0.0));
      float c = hash(i + vec2(0.0, 1.0)), d = hash(i + vec2(1.0, 1.0));
      return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
    }
    float fbm(vec2 p){
      float v = 0.0, a = 0.5;
      for (int i = 0; i < 4; i++){ v += a * noise(p); p *= 2.03; a *= 0.5; }
      return v;
    }

    void main(){
      vec2 p = (uv - 0.5) * 2.0;
      p.x *= u_res.x / u_res.y;
      float r = length(p);
      float ang = atan(p.y, p.x);
      float t = u_time * 0.45;

      float n  = fbm(p * 2.2 + vec2(t * 0.55, -t * 0.35));
      float n2 = fbm(p * 4.8 - vec2(t * 0.85, t * 0.45) + n * 0.65);

      float core   = smoothstep(0.38, 0.0, r);
      float plasma = core * (0.32 + 1.05 * n2);
      float hot    = exp(-r * r * 8.0) * (0.55 + 0.95 * u_amp);

      float r1 = smoothstep(0.020, 0.0, abs(r - 0.44)) * (0.62 + 0.38 * sin(ang * 6.0 + t * 1.6));
      float r2 = smoothstep(0.012, 0.0, abs(r - 0.60)) * (0.55 + 0.45 * sin(ang * 12.0 - t * 1.2));
      float r3 = smoothstep(0.008, 0.0, abs(r - 0.74)) * (0.50 + 0.50 * sin(ang * 24.0 + t * 0.8));
      float r4 = smoothstep(0.006, 0.0, abs(r - 0.88)) * 0.42;
      float halo = exp(-max(r - 0.24, 0.0) * 2.6) * 0.48;
      float scan = 0.05 * sin(uv.y * 620.0 - u_time * 2.0);

      float pulse = 1.0 + 0.55 * u_amp;
      float alpha = plasma * 0.80 * pulse + hot * 0.95 + r1 * 0.95 + r2 * 0.75
                  + r3 * 0.55 + r4 * 0.40 + halo * (0.30 + 0.45 * u_amp) + scan * 0.04;

      vec3 base = mix(u_accent, vec3(1.0, 0.72, 0.34), u_warm * 0.50);
      vec3 col = base * alpha;
      col += vec3(0.72, 0.94, 1.0) * hot * 0.75;
      col += vec3(0.85, 0.98, 1.0) * core * 0.12;

      float edge = 1.0 - smoothstep(0.95, 1.30, r);
      gl_FragColor = vec4(col * edge, clamp(alpha, 0.0, 1.0) * edge);
    }
  `;

  function hexToRgb(hex) {
    const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || '#37d8ff');
    if (!m) return [0.216, 0.847, 1.0];
    return [parseInt(m[1], 16) / 255, parseInt(m[2], 16) / 255, parseInt(m[3], 16) / 255];
  }

  class Orb {
    constructor(canvas, accent) {
      this.canvas = canvas;
      this.accent = hexToRgb(accent);
      this.amp = 0;
      this.warm = 0;
      this.time = 0;
      this.last = performance.now();
      this.gl = canvas.getContext('webgl', { alpha: true, antialias: true, premultipliedAlpha: false });
      if (this.gl) {
        try { this._initGL(); } catch (e) { this.gl = null; }
      }
      if (!this.gl) this._init2D();
      this._resize();
      window.addEventListener('resize', () => this._resize());
      this._loop = this._loop.bind(this);
      requestAnimationFrame(this._loop);
    }

    _initGL() {
      const gl = this.gl;
      const sh = (type, src) => {
        const s = gl.createShader(type);
        gl.shaderSource(s, src);
        gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
        return s;
      };
      const prog = gl.createProgram();
      gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
      gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
      gl.useProgram(prog);

      const buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(prog, 'p');
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

      this.u = {
        res: gl.getUniformLocation(prog, 'u_res'),
        time: gl.getUniformLocation(prog, 'u_time'),
        amp: gl.getUniformLocation(prog, 'u_amp'),
        warm: gl.getUniformLocation(prog, 'u_warm'),
        accent: gl.getUniformLocation(prog, 'u_accent'),
      };
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
      gl.clearColor(0, 0, 0, 0);
    }

    _init2D() {
      this.ctx = this.canvas.getContext('2d');
    }

    _resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = this.canvas.getBoundingClientRect();
      this.w = Math.max(2, Math.floor(rect.width * dpr));
      this.h = Math.max(2, Math.floor(rect.height * dpr));
      this.canvas.width = this.w;
      this.canvas.height = this.h;
      if (this.gl) this.gl.viewport(0, 0, this.w, this.h);
    }

    setAmp(v) { this.amp += (Math.max(0, Math.min(1, v)) - this.amp) * 0.18; }
    setWarm(on) { this.warm += ((on ? 1 : 0) - this.warm) * 0.06; }

    _loop(now) {
      const dt = Math.min(0.1, (now - this.last) / 1000) || 0.016;
      this.last = now;
      this.time += dt;
      this.amp *= 0.985;
      if (this.gl) {
        const gl = this.gl;
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.uniform2f(this.u.res, this.w, this.h);
        gl.uniform1f(this.u.time, this.time);
        gl.uniform1f(this.u.amp, this.amp);
        gl.uniform1f(this.u.warm, this.warm);
        gl.uniform3fv(this.u.accent, this.accent);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      } else if (this.ctx) {
        this._draw2D();
      }
      requestAnimationFrame(this._loop);
    }

    _draw2D() {
      const c = this.ctx, w = this.w, h = this.h;
      c.clearRect(0, 0, w, h);
      const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2;
      const [r, g, b] = this.accent.map((v) => Math.round(v * 255));
      const glow = 0.55 + this.amp * 0.45;
      const grad = c.createRadialGradient(cx, cy, 0, cx, cy, R * 0.9);
      grad.addColorStop(0, `rgba(${r},${g},${b},${0.85 * glow})`);
      grad.addColorStop(0.35, `rgba(${r},${g},${b},${0.30 * glow})`);
      grad.addColorStop(0.7, `rgba(${r},${g},${b},0.05)`);
      grad.addColorStop(1, 'rgba(0,0,0,0)');
      c.fillStyle = grad;
      c.beginPath(); c.arc(cx, cy, R, 0, Math.PI * 2); c.fill();
      c.strokeStyle = `rgba(${r},${g},${b},0.55)`;
      c.lineWidth = Math.max(1, R * 0.008);
      for (const k of [0.62, 0.83]) {
        c.beginPath(); c.arc(cx, cy, R * k, 0, Math.PI * 2); c.stroke();
      }
      c.beginPath();
      c.arc(cx, cy, R * 0.62, this.time * 1.6, this.time * 1.6 + Math.PI * 1.2);
      c.strokeStyle = `rgba(255,255,255,${0.35 + this.amp * 0.4})`;
      c.lineWidth = Math.max(1.5, R * 0.012);
      c.stroke();
    }
  }

  window.Orb = Orb;
})();
