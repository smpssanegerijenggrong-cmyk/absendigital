(()=>{
  const menu=document.getElementById('mobile-menu'), sidebar=document.getElementById('sidebar'), backdrop=document.getElementById('backdrop');
  if(menu&&sidebar&&backdrop){const close=()=>{sidebar.classList.remove('open');backdrop.hidden=true};menu.addEventListener('click',()=>{sidebar.classList.add('open');backdrop.hidden=false});backdrop.addEventListener('click',close);document.querySelectorAll('.sidebar a').forEach(a=>a.addEventListener('click',close))}
  const select=document.getElementById('reasonSelect'),custom=document.getElementById('customReasonField');
  if(select&&custom){const toggle=()=>{custom.hidden=select.value!=='Lainnya';custom.querySelector('textarea').required=select.value==='Lainnya'};select.addEventListener('change',toggle);toggle()}
})();
