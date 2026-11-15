// This renderer runs inside the local WebView on both clients.
function drawBand() {
  const canvas = document.createElement('canvas');
  document.body.style.cssText = 'margin:0;background:white;overflow:hidden';
  canvas.style.cssText = 'display:block;width:100vw;height:100vh;touch-action:none;cursor:grab';
  canvas.setAttribute('aria-label', 'Rotate the Vexo Band with its green match light');
  canvas.tabIndex = 0;
  document.body.appendChild(canvas);
  const ctx = canvas.getContext('2d');
  let yaw = -0.72, pitch = -0.16;
  const mesh = [];
  function point(t, x, depth) {
    return [x, (1.12 + depth) * Math.sin(t), (0.84 + depth) * Math.cos(t)];
  }
  function band(start, end, steps, width, inside, outside, housing) {
    const bevel = 0.035;
    const contour = [[-width+bevel,outside],[width-bevel,outside],[width,outside-bevel],
      [width,inside+bevel],[width-bevel,inside],[-width+bevel,inside],[-width,inside+bevel],[-width,outside-bevel]];
    for(let i=0;i<steps;i++) {
      const t=start+(end-start)*i/steps, u=start+(end-start)*(i+1)/steps;
      contour.forEach(([x,d],j)=>{
        const [xx,dd]=contour[(j+1)%contour.length];
        const base=housing ? 48 : j===0 && i%2===0 ? 66 : 50;
        mesh.push({vertices:[point(t,x,d),point(t,xx,dd),point(u,xx,dd),point(u,x,d)],base});
      });
    }
    if(housing) for(const t of [start,end])mesh.push({vertices:contour.map(([x,d])=>point(t,x,d)),base:45});
  }
  band(0,Math.PI*2,100,.37,-.085,.04,false);
  band(-.46,.6,20,.405,.035,.135,true);
  const led = [];
  for(let i=0;i<32;i++) {
    const a=2*Math.PI*i/32;
    led.push(point(.29+.029*Math.sin(a),.17*Math.cos(a),.143));
  }
  mesh.push({vertices:led,led:true});
  function render() {
    const w=innerWidth,h=innerHeight,dpr=Math.min(devicePixelRatio,2);
    canvas.width=Math.round(w*dpr); canvas.height=Math.round(h*dpr);
    ctx.setTransform(dpr,0,0,dpr,0,0);
    const scale=Math.min(h*.37,w*.35);
    const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
    const faces=mesh.map(face=>{
      const pts=face.vertices.map(([x,y,z])=>{
        const side=x*cy+z*sy, depth=z*cy-x*sy;
        return [side,y*cp-depth*sp,depth*cp+y*sp];
      });
      return {face,pts,z:pts.reduce((sum,p)=>sum+p[2],0)/pts.length};
    }).sort((a,b)=>a.z-b.z);
    for(const {face,pts} of faces) {
      const [a,b,c]=pts;
      const ux=b[0]-a[0],uy=b[1]-a[1],uz=b[2]-a[2];
      const vx=c[0]-a[0],vy=c[1]-a[1],vz=c[2]-a[2];
      const nx=uy*vz-uz*vy,ny=uz*vx-ux*vz,nz=ux*vy-uy*vx;
      const l=Math.hypot(nx,ny,nz)||1;
      const shade=face.base*(.55+.75*Math.abs((-.38*nx+.75*ny+.54*nz)/l));
      ctx.fillStyle=face.led?'#55ff64':'rgb('+[shade,shade+2,shade+3].join(',')+')';
      ctx.beginPath();
      pts.forEach(([x,y,z],i)=>{
        const k=scale*5/(5-z);
        if(i===0)ctx.moveTo(w/2+x*k,h/2-y*k);else ctx.lineTo(w/2+x*k,h/2-y*k);
      });
      ctx.closePath();
      ctx.shadowColor=face.led?'#12ff50':'transparent';ctx.shadowBlur=face.led?12:0;
      ctx.fill();ctx.strokeStyle=ctx.fillStyle;ctx.lineWidth=.55;ctx.stroke();
    }
  }
  let last=null;
  canvas.onpointerdown=e=>{canvas.setPointerCapture(e.pointerId);last=[e.clientX,e.clientY]};
  canvas.onpointermove=e=>{
    if(!last)return;
    yaw+=(e.clientX-last[0])*.016;pitch+=(e.clientY-last[1])*.014;
    last=[e.clientX,e.clientY];render();
  };
  canvas.onpointerup=canvas.onpointercancel=()=>{last=null};
  canvas.onkeydown=e=>{
    if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;
    e.preventDefault();
    if(e.key==='ArrowLeft')yaw-=.2;if(e.key==='ArrowRight')yaw+=.2;
    if(e.key==='ArrowUp')pitch-=.2;if(e.key==='ArrowDown')pitch+=.2;
    render();
  };
  window.addEventListener('resize',render);render();
}
if(typeof module!=='undefined') module.exports=drawBand;
