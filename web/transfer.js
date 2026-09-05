/* Durable, sequential uploads. Only server-acknowledged bytes count as progress. */
(() => {
  'use strict';
  const tasks=[], root=document.getElementById('uploadTasks');
  const status=document.getElementById('uploadStatus');
  const picker=document.getElementById('picker'), drop=document.getElementById('drop');
  const hash=WindBridgeHash.digest;
  let pumping=false;
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  async function request(path, options={}, task=null){
    const controller=new AbortController();
    if(task) task.controller=controller;
    const timeout=setTimeout(()=>controller.abort(),60000);
    try {
      const response=await fetch('/api/uploads'+path,{...options,signal:controller.signal,
        headers:{'X-WindBridge-Token':token,...options.headers}});
      const body=await response.json().catch(()=>({}));
      if(!response.ok){const error=new Error(body.error||`请求失败 (${response.status})`);error.status=response.status;throw error;}
      return body;
    } finally {clearTimeout(timeout);if(task?.controller===controller) task.controller=null;}
  }
  function render(){
    root.replaceChildren();
    for(const task of tasks){
      const row=document.createElement('div');row.className='upload-task';
      const title=document.createElement('strong');title.textContent=task.name;row.append(title);
      const info=document.createElement('div');info.className='meta';
      info.textContent=`${task.message} · 已保存 ${fmt(task.session?.offset||0)} / ${fmt(task.size)}`;row.append(info);
      const progress=document.createElement('progress');progress.max=task.size||1;
      progress.value=task.done?(task.size||1):(task.session?.offset||0);progress.setAttribute('aria-label',task.name+' 已保存进度');row.append(progress);
      const actions=document.createElement('div');actions.className='row';
      const button=(label,action)=>{const b=document.createElement('button');b.className='secondary';b.textContent=label;b.onclick=action;actions.append(b);};
      if(!task.done && !task.cancelled){
        if(task.running||task.queued) button('暂停',()=>{task.paused=true;task.queued=false;task.controller?.abort();task.message='已暂停';render();});
        else button(task.file?'继续':'选择原文件续传',()=>{
          if(!task.file){picker.click();return;}
          task.paused=false;task.queued=true;task.message='等待继续';render();pump();
        });
      }
      if(!task.cancelled)button(task.done?'移除记录':'取消任务',()=>cancel(task));
      row.append(actions);root.append(row);
    }
  }
  async function fingerprint(file){
    const metadata=new TextEncoder().encode(JSON.stringify([file.name,file.size,file.lastModified]));
    const first=new Uint8Array(await file.slice(0,65536).arrayBuffer());
    const last=new Uint8Array(await file.slice(Math.max(0,file.size-65536)).arrayBuffer());
    const bytes=new Uint8Array(metadata.length+first.length+last.length);
    bytes.set(metadata);bytes.set(first,metadata.length);bytes.set(last,metadata.length+first.length);
    return hash(bytes);
  }
  async function verifyPrefix(task){
    const session=task.session;
    task.message='正在核对已保存分块';render();
    for(let i=0;i<session.hashes.length;i++){
      if(task.paused||task.cancelled)return false;
      const bytes=await task.file.slice(i*session.chunk_size,Math.min((i+1)*session.chunk_size,session.size)).arrayBuffer();
      if(await hash(bytes)!==session.hashes[i]) throw new Error('所选文件与已保存内容不同，请取消此任务后重新上传');
      await wait(0);
    }
    return true;
  }
  async function run(task){
    let retries=0;
    while(!task.paused&&!task.cancelled){
      try {
        // Do not abort initialization: keep its returned ID for pause/cancel.
        if(!task.session) task.session=await request('',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({name:task.name,size:task.size,fingerprint:task.fingerprint})});
        else task.session=await request('/'+task.session.id,{},task);
        if(task.paused||task.cancelled)return;
        if(!await verifyPrefix(task))return;
        while(task.session.offset<task.size){
          if(task.paused||task.cancelled)return;
          const offset=task.session.offset;
          const bytes=await task.file.slice(offset,offset+task.session.chunk_size).arrayBuffer();
          const digest=await hash(bytes);
          if(task.paused||task.cancelled)return;
          task.message='正在传送';render();
          task.session=await request('/'+task.session.id,{method:'PUT',body:bytes,
            headers:{'Content-Type':'application/octet-stream','Upload-Offset':String(offset),'X-Chunk-SHA256':digest}},task);
          retries=0;render();await wait(0);
        }
        if(task.paused||task.cancelled)return;
        task.message='正在校验并保存文件';render();
        task.session=await request('/'+task.session.id+'/complete',{method:'POST'},task);
        task.done=true;task.message='已送达 · SHA-256 校验通过';return;
      } catch(error){
        if(task.paused||task.cancelled)return;
        if(error.status===401){block('配对码已失效，请重新扫描电脑端二维码');throw error;}
        if(error.status===404){task.session=null;throw new Error('续传任务已过期，点击继续重新上传');}
        const retryable=!error.status||[409,500,502,503,504].includes(error.status);
        if(!retryable||retries>=3)throw error;
        task.message=`连接中断或进度变化，正在重试 (${++retries}/3)`;render();
        await wait(1000*2**(retries-1));
      }
    }
  }
  async function pump(){
    if(pumping)return;pumping=true;
    try{
      let task;
      while((task=tasks.find(t=>t.queued&&!t.paused&&!t.cancelled&&!t.done))){
        task.queued=false;task.running=true;render();
        task.promise=run(task).catch(error=>{task.message=error.message+'；进度已保留';task.paused=true;});
        await task.promise;task.running=false;render();
      }
    }finally{pumping=false;}
  }
  async function cancel(task){
    task.cancelled=true;task.queued=false;task.controller?.abort();
    task.message='正在取消';render();
    try{
      await task.promise;
      if(task.session)await request('/'+task.session.id,{method:'DELETE'});
      tasks.splice(tasks.indexOf(task),1);render();
    }catch(error){task.cancelled=false;task.paused=true;task.message=error.message+'；取消未完成，请重试';render();}
  }
  async function add(files){
    for(const file of files){
      if(file.size>2*1024**3){status.textContent=`${file.name} 超过单文件 2 GiB 上限`;continue;}
      try{
        status.textContent='正在识别文件…';const key=await fingerprint(file);
        let task=tasks.find(t=>t.fingerprint===key);
        if(task?.running||task?.queued||task?.done)continue;
        if(!task){task={name:file.name,size:file.size,fingerprint:key};tasks.push(task);}
        Object.assign(task,{file,paused:false,cancelled:false,queued:true,message:'等待传送'});render();pump();
      }catch(error){status.textContent=error.message;}
    }
    picker.value='';status.textContent='刷新后需重新选择原文件；重启电脑端后需重新配对。';
  }
  async function restore(){
    try{
      const data=await request('');
      for(const session of data.uploads){
        if(tasks.some(t=>t.session?.id===session.id||t.fingerprint===session.fingerprint))continue;
        tasks.push({name:session.name,size:session.size,fingerprint:session.fingerprint,session,
          done:session.status==='completed',paused:true,message:session.status==='completed'?'已完成记录':'等待选择原文件续传'});
      }
      render();
    }catch(error){status.textContent=error.message;if(error.status===401)block(error.message);}
  }
  ['dragenter','dragover'].forEach(type=>drop.addEventListener(type,e=>{e.preventDefault();drop.classList.add('drag');}));
  ['dragleave','drop'].forEach(type=>drop.addEventListener(type,e=>{e.preventDefault();drop.classList.remove('drag');}));
  drop.addEventListener('drop',e=>add([...e.dataTransfer.files]));
  picker.addEventListener('change',()=>add([...picker.files]));
  document.getElementById('refreshUploads').onclick=restore;
  if(token)restore();
})();
