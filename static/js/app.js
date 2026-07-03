const service=document.getElementById('service'), pages=document.getElementById('pages'), copies=document.getElementById('copies'), total=document.getElementById('total'), printer=document.getElementById('printer');
function calc(){const opt=service.options[service.selectedIndex]; const rate=parseInt(opt.dataset.rate||0); const p=Math.max(1, parseInt(pages.value||1)); const c=Math.max(1, parseInt(copies.value||1)); total.textContent=rate*p*c; printer.textContent=opt.dataset.printer||'';}
[service,pages,copies].forEach(x=>x.addEventListener('input',calc)); calc();
