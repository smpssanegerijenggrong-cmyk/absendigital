/* Scan otomatis QR + GPS; fallback BarcodeDetector bila library kamera tidak tersedia. */
(()=>{
  const start=document.getElementById('startScanner'),stop=document.getElementById('stopScanner');
  if(!start||!stop)return;
  const status=document.getElementById('scan-status'),result=document.getElementById('scan-result'),reader=document.getElementById('qr-reader');
  const config=document.getElementById('scan-conf');
  const csrf=config.dataset.csrf,endpoint=config.dataset.endpoint;
  let scanner=null,stream=null,video=null,busy=false,stopped=true,requestId=0,lastRaw='',lastAt=0;
  const setStatus=(message,type='')=>{status.className='scan-message '+type;status.textContent=message};
  const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
  const once=async(raw)=>{
    if(busy||!raw||stopped)return;
    const token=String(raw).trim(),now=Date.now();
    if(token===lastRaw&&now-lastAt<4000)return;
    lastRaw=token;lastAt=now;busy=true;
    try{
      setStatus('QR terbaca. Memverifikasi GPS dan menyimpan waktu server...');
      const pos=await new Promise((resolve,reject)=>navigator.geolocation.getCurrentPosition(resolve,reject,{enableHighAccuracy:true,maximumAge:0,timeout:12000}));
      const response=await fetch(endpoint,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({token,latitude:pos.coords.latitude,longitude:pos.coords.longitude,accuracy:pos.coords.accuracy})});
      const data=await response.json();
      if(!response.ok){const message=typeof data.detail==='string'?data.detail:'Pemindaian gagal atau sesi berakhir.';setStatus(message,'error');result.innerHTML='<div class="result-error"><div>!</div><h3>Absensi ditolak</h3><p>'+esc(message)+'</p></div>';return}
      const late=data.late_seconds?Math.floor(data.late_seconds/60)+' menit '+(data.late_seconds%60)+' detik':'—';
      result.innerHTML='<div class="result-success"><div class="result-check">✓</div><h3>'+esc(data.student)+'</h3><p>'+esc(data.class_name)+' · NISN '+esc(data.nisn||'—')+'</p><span class="tag '+(data.status==='HADIR'?'hadir':'terlambat')+'">'+esc(data.status)+'</span><dl><div><dt>Jam absen WIB</dt><dd>'+esc(data.time)+'</dd></div><div><dt>Tanggal</dt><dd>'+esc(data.day)+'</dd></div><div><dt>Keterlambatan</dt><dd>'+esc(late)+'</dd></div><div><dt>Jarak GPS</dt><dd>'+esc(data.distance_m)+' meter</dd></div></dl></div>';
      setStatus('✓ Berhasil menyimpan absensi '+data.student+' pada '+data.time+' WIB. Lanjutkan scan siswa berikutnya.','success');
      if(navigator.vibrate)navigator.vibrate(80);
    }catch(err){const msg=err.code?'GPS gagal: '+err.message:'Koneksi server gagal: '+err.message;setStatus(msg,'error');result.innerHTML='<div class="result-error"><div>!</div><h3>Gagal memproses</h3><p>'+esc(msg)+'</p></div>'}
    finally{busy=false}
  };
  const stopAll=async()=>{stopped=true;requestId++;if(scanner){const s=scanner;scanner=null;try{await s.stop()}catch(_){ }try{await s.clear()}catch(_){ }}if(stream){stream.getTracks().forEach(t=>t.stop());stream=null}if(video){video.remove();video=null}reader.innerHTML='<div class="reader-idle"><div class="reader-target"><span>▣</span></div><h3>Kamera dimatikan</h3><p>Tekan Mulai Scanner untuk mengaktifkan.</p></div>';setStatus('Kamera berhenti.')};
  const startNative=async()=>{
    if(!('BarcodeDetector' in window))throw new Error('Pemindai QR belum tersedia di browser ini. Gunakan Chrome/Edge terbaru atau sambungan internet untuk pustaka scanner.');
    const detector=new BarcodeDetector({formats:['qr_code']});
    stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});
    reader.innerHTML='';video=document.createElement('video');video.autoplay=true;video.muted=true;video.playsInline=true;video.style.width='100%';reader.appendChild(video);video.srcObject=stream;await video.play();
    const id=++requestId;const loop=async()=>{if(stopped||id!==requestId)return;try{if(!busy){const values=await detector.detect(video);if(values?.length)await once(values[0].rawValue)}}catch(_){}if(!stopped&&id===requestId)requestAnimationFrame(loop)};
    loop();
  };
  const startHtml5=async()=>{
    reader.innerHTML='';scanner=new Html5Qrcode('qr-reader',{verbose:false});
    await scanner.start({facingMode:'environment'},{fps:12,qrbox:{width:225,height:225}},raw=>{void once(raw)},()=>{});
  };
  start.addEventListener('click',async()=>{
    if(!stopped)return;
    if(!window.isSecureContext||!navigator.mediaDevices){setStatus('Kamera dan GPS membutuhkan HTTPS atau localhost.','error');return}
    stopped=false;setStatus('Meminta izin kamera...');
    start.disabled=true;
    try{if(window.Html5Qrcode)await startHtml5();else await startNative();setStatus('Kamera aktif. Arahkan QR siswa ke kotak pemindai.')}
    catch(err){setStatus('Kamera tidak bisa dibuka: '+err.message,'error');await stopAll()}
    finally{start.disabled=false}
  });
  stop.addEventListener('click',()=>{void stopAll()});
  window.addEventListener('pagehide',()=>{void stopAll()});
})();
