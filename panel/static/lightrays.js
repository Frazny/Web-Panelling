(function() {
    const DEFAULT_COLOR = '#ffffff';
    function hexToRgb(hex) {
        const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
        return m ? [parseInt(m[1], 16) / 255, parseInt(m[2], 16) / 255, parseInt(m[3], 16) / 255] : [1, 1, 1];
    }
    function getAnchorAndDir(origin, w, h) {
        const outside = 0.2;
        switch (origin) {
            case 'top-left': return { anchor: [0, -outside * h], dir: [0, 1] };
            case 'top-right': return { anchor: [w, -outside * h], dir: [0, 1] };
            case 'left': return { anchor: [-outside * w, 0.5 * h], dir: [1, 0] };
            case 'right': return { anchor: [(1 + outside) * w, 0.5 * h], dir: [-1, 0] };
            case 'bottom-left': return { anchor: [0, (1 + outside) * h], dir: [0, -1] };
            case 'bottom-center': return { anchor: [0.5 * w, (1 + outside) * h], dir: [0, -1] };
            case 'bottom-right': return { anchor: [w, (1 + outside) * h], dir: [0, -1] };
            default: return { anchor: [0.5 * w, -outside * h], dir: [0, 1] };
        }
    }
    class LightRaysEngine {
        constructor(container, options = {}) {
            this.container = container;
            this.options = Object.assign({
                raysOrigin: 'top-center', raysColor: DEFAULT_COLOR, raysSpeed: 1,
                lightSpread: 0.5, rayLength: 3, pulsating: false, fadeDistance: 1,
                saturation: 1, followMouse: true, mouseInfluence: 0.1, noiseAmount: 0, distortion: 0
            }, options);
            this.mousePos = { x: 0.5, y: 0.5 };
            this.smoothMouse = { x: 0.5, y: 0.5 };
            this.animationId = null;
            this.gl = null;
            this.program = null;
            this.init();
        }
        init() {
            const canvas = document.createElement('canvas');
            canvas.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;';
            this.container.appendChild(canvas);
            const gl = canvas.getContext('webgl', { alpha: true, antialias: false });
            if (!gl) return;
            this.gl = gl;
            const vertSrc = `attribute vec2 position;varying vec2 vUv;void main(){vUv=position*0.5+0.5;gl_Position=vec4(position,0.0,1.0);}`;
            const fragSrc = `precision highp float;
uniform float iTime;uniform vec2 iResolution;uniform vec2 rayPos;uniform vec2 rayDir;
uniform vec3 raysColor;uniform float raysSpeed;uniform float lightSpread;uniform float rayLength;
uniform float pulsating;uniform float fadeDistance;uniform float saturation;
uniform vec2 mousePos;uniform float mouseInfluence;uniform float noiseAmount;uniform float distortion;
varying vec2 vUv;
float noise(vec2 st){return fract(sin(dot(st.xy,vec2(12.9898,78.233)))*43758.5453123);}
float rayStrength(vec2 raySource,vec2 rayRefDirection,vec2 coord,float seedA,float seedB,float speed){
    vec2 sourceToCoord=coord-raySource;vec2 dirNorm=normalize(sourceToCoord);
    float cosAngle=dot(dirNorm,rayRefDirection);
    float distortedAngle=cosAngle+distortion*sin(iTime*2.0+length(sourceToCoord)*0.01)*0.2;
    float spreadFactor=pow(max(distortedAngle,0.0),1.0/max(lightSpread,0.001));
    float distance=length(sourceToCoord);float maxDistance=iResolution.x*rayLength;
    float lengthFalloff=clamp((maxDistance-distance)/maxDistance,0.0,1.0);
    float fadeFalloff=clamp((iResolution.x*fadeDistance-distance)/(iResolution.x*fadeDistance),0.5,1.0);
    float pulse=pulsating>0.5?(0.8+0.2*sin(iTime*speed*3.0)):1.0;
    float baseStrength=clamp((0.45+0.15*sin(distortedAngle*seedA+iTime*speed))+(0.3+0.2*cos(-distortedAngle*seedB+iTime*speed)),0.0,1.0);
    return baseStrength*lengthFalloff*fadeFalloff*spreadFactor*pulse;}
void mainImage(out vec4 fragColor,in vec2 fragCoord){
    vec2 coord=vec2(fragCoord.x,iResolution.y-fragCoord.y);
    vec2 finalRayDir=rayDir;
    if(mouseInfluence>0.0){vec2 mouseScreenPos=mousePos*iResolution.xy;vec2 mouseDirection=normalize(mouseScreenPos-rayPos);finalRayDir=normalize(mix(rayDir,mouseDirection,mouseInfluence));}
    vec4 rays1=vec4(1.0)*rayStrength(rayPos,finalRayDir,coord,36.2214,21.11349,1.5*raysSpeed);
    vec4 rays2=vec4(1.0)*rayStrength(rayPos,finalRayDir,coord,22.3991,18.0234,1.1*raysSpeed);
    fragColor=rays1*0.5+rays2*0.4;
    if(noiseAmount>0.0){float n=noise(coord*0.01+iTime*0.1);fragColor.rgb*=(1.0-noiseAmount+noiseAmount*n);}
    float brightness=1.0-(coord.y/iResolution.y);
    fragColor.x*=0.1+brightness*0.8;fragColor.y*=0.3+brightness*0.6;fragColor.z*=0.5+brightness*0.5;
    if(saturation!=1.0){float gray=dot(fragColor.rgb,vec3(0.299,0.587,0.114));fragColor.rgb=mix(vec3(gray),fragColor.rgb,saturation);}
    fragColor.rgb*=raysColor;}
void main(){vec4 color;mainImage(color,gl_FragCoord.xy);gl_FragColor=color;}`;
            const vert = this.createShader(gl, gl.VERTEX_SHADER, vertSrc);
            const frag = this.createShader(gl, gl.FRAGMENT_SHADER, fragSrc);
            const program = gl.createProgram();
            gl.attachShader(program, vert); gl.attachShader(program, frag); gl.linkProgram(program);
            if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;
            this.program = program; gl.useProgram(program);
            const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
            gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]), gl.STATIC_DRAW);
            const pos = gl.getAttribLocation(program, 'position');
            gl.enableVertexAttribArray(pos); gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);
            this.uLocations = {};
            ['iTime','iResolution','rayPos','rayDir','raysColor','raysSpeed','lightSpread','rayLength',
             'pulsating','fadeDistance','saturation','mousePos','mouseInfluence','noiseAmount','distortion'
            ].forEach(n => this.uLocations[n] = gl.getUniformLocation(program, n));
            this.resize = this.resize.bind(this);
            window.addEventListener('resize', this.resize); this.resize();
            if (this.options.followMouse) {
                this.onMouseMove = (e) => {
                    const rect = this.container.getBoundingClientRect();
                    this.mousePos.x = (e.clientX - rect.left) / rect.width;
                    this.mousePos.y = (e.clientY - rect.top) / rect.height;
                };
                window.addEventListener('mousemove', this.onMouseMove);
            }
            this.render = this.render.bind(this);
            this.animationId = requestAnimationFrame(this.render);
        }
        createShader(gl, type, source) {
            const shader = gl.createShader(type);
            gl.shaderSource(shader, source); gl.compileShader(shader);
            if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) { gl.deleteShader(shader); return null; }
            return shader;
        }
        resize() {
            if (!this.gl || !this.container) return;
            const dpr = Math.min(window.devicePixelRatio || 1, 2);
            const w = (this.container.clientWidth || window.innerWidth) * dpr;
            const h = (this.container.clientHeight || window.innerHeight) * dpr;
            this.gl.canvas.width = w; this.gl.canvas.height = h;
            this.gl.viewport(0, 0, w, h);
            this.gl.useProgram(this.program);
            this.gl.uniform2f(this.uLocations.iResolution, w, h);
            const { anchor, dir } = getAnchorAndDir(this.options.raysOrigin, w, h);
            this.gl.uniform2f(this.uLocations.rayPos, anchor[0], anchor[1]);
            this.gl.uniform2f(this.uLocations.rayDir, dir[0], dir[1]);
        }
        render(t) {
            if (!this.gl || !this.program) return;
            const gl = this.gl; gl.useProgram(this.program);
            gl.uniform1f(this.uLocations.iTime, t * 0.001);
            const c = hexToRgb(this.options.raysColor);
            gl.uniform3f(this.uLocations.raysColor, c[0], c[1], c[2]);
            gl.uniform1f(this.uLocations.raysSpeed, this.options.raysSpeed);
            gl.uniform1f(this.uLocations.lightSpread, this.options.lightSpread);
            gl.uniform1f(this.uLocations.rayLength, this.options.rayLength);
            gl.uniform1f(this.uLocations.pulsating, this.options.pulsating ? 1.0 : 0.0);
            gl.uniform1f(this.uLocations.fadeDistance, this.options.fadeDistance);
            gl.uniform1f(this.uLocations.saturation, this.options.saturation);
            gl.uniform1f(this.uLocations.mouseInfluence, this.options.mouseInfluence);
            gl.uniform1f(this.uLocations.noiseAmount, this.options.noiseAmount);
            gl.uniform1f(this.uLocations.distortion, this.options.distortion);
            if (this.options.followMouse && this.options.mouseInfluence > 0.0) {
                const s = 0.92;
                this.smoothMouse.x = this.smoothMouse.x * s + this.mousePos.x * (1 - s);
                this.smoothMouse.y = this.smoothMouse.y * s + this.mousePos.y * (1 - s);
                gl.uniform2f(this.uLocations.mousePos, this.smoothMouse.x, this.smoothMouse.y);
            }
            gl.drawArrays(gl.TRIANGLES, 0, 6);
            this.animationId = requestAnimationFrame(this.render);
        }
        destroy() {
            if (this.animationId) cancelAnimationFrame(this.animationId);
            if (this.onMouseMove) window.removeEventListener('mousemove', this.onMouseMove);
            window.removeEventListener('resize', this.resize);
            if (this.gl && this.gl.canvas && this.gl.canvas.parentNode) this.gl.canvas.parentNode.removeChild(this.gl.canvas);
        }
    }
    window.LightRaysEngine = LightRaysEngine;
    document.addEventListener('DOMContentLoaded', () => {
        if (document.getElementById('light-rays-bg')) return;
        const bg = document.createElement('div');
        bg.id = 'light-rays-bg';
        bg.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;pointer-events:none;z-index:-1;overflow:hidden;';
        document.body.prepend(bg);
        new LightRaysEngine(bg, {
            raysOrigin: 'top-center', raysColor: '#ffffff', raysSpeed: 1,
            lightSpread: 0.5, rayLength: 3, followMouse: true, mouseInfluence: 0.1,
            noiseAmount: 0, distortion: 0, pulsating: false, fadeDistance: 1, saturation: 1
        });
    });
})();
