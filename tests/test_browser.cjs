/* Optional: requires Playwright and an installed Chrome browser. No personal files/settings are used. */
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const {randomBytes,createHash} = require('node:crypto');
const root=path.resolve(__dirname,'..'), chunk=4*1024*1024;
let child,browser,folder,port,token=randomBytes(24).toString('hex');
const hash=data=>createHash('sha256').update(data).digest('hex');
async function start(){
  child=spawn(process.env.WINDBRIDGE_TEST_PYTHON||path.join(root,'.venv','Scripts','python.exe'),
    [path.join(__dirname,'browser_server.py'),path.join(folder,'incoming'),String(port||0)],
    {cwd:root,windowsHide:true,env:{...process.env,WINDBRIDGE_TEST_TOKEN:token},stdio:['ignore','pipe','pipe']});
  port=await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('Test server startup timed out')),10000);
    child.stdout.on('data',data=>{const match=/PORT:(\d+)/.exec(String(data));if(match){clearTimeout(timer);resolve(Number(match[1]));}});
    child.once('error',error=>{clearTimeout(timer);reject(error);});
    child.once('exit',()=>{clearTimeout(timer);reject(new Error('Test server stopped'));});
  });
}
async function stop(){if(child&&child.exitCode===null){const exited=once(child,'exit');child.kill();await exited;}}
async function api(endpoint,options={}){
  return fetch(`http://127.0.0.1:${port}/api/uploads${endpoint}`,{...options,headers:{'X-WindBridge-Token':token,...options.headers}});
}
async function open(page){
  await page.goto(`http://127.0.0.1:${port}/?token=${encodeURIComponent(token)}`);
  await page.getByRole('button',{name:'发送文件',exact:true}).click();
}
async function main(){
  folder=await fs.mkdtemp(path.join(os.tmpdir(),'windbridge-browser-'));
  const data=randomBytes(chunk*2+917), file=path.join(folder,'resume.bin');await fs.writeFile(file,data);
  await start();browser=await chromium.launch({channel:'chrome',headless:true});
  const context=await browser.newContext({viewport:{width:390,height:844}});
  // LAN HTTP does not expose Web Crypto. Exercise the same fallback on loopback.
  await context.addInitScript(()=>Object.defineProperty(globalThis,'crypto',{value:undefined}));
  const page=await context.newPage(), errors=[];page.on('pageerror',error=>errors.push(error.message));
  await open(page);
  let secondResolve;const second=new Promise(resolve=>secondResolve=resolve);
  await page.route('**/api/uploads/*',async route=>{
    if(route.request().method()==='PUT'&&Number(route.request().headers()['upload-offset'])>=chunk){
      secondResolve();await new Promise(resolve=>setTimeout(resolve,500));
      await route.abort().catch(()=>{});return;
    }
    await route.continue();
  });
  await page.locator('#picker').setInputFiles(file);await second;
  await page.getByRole('button',{name:'暂停',exact:true}).click();
  await page.getByRole('button',{name:'继续',exact:true}).waitFor();
  let sessions=(await (await api('')).json()).uploads;assert.equal(sessions[0].offset,chunk);
  await page.unrouteAll({behavior:'wait'});
  await stop();token=randomBytes(24).toString('hex');await start();
  await page.reload();await page.locator('#blocked').waitFor({state:'visible'});
  await open(page);
  await page.getByRole('button',{name:'选择原文件续传',exact:true}).waitFor();
  const offsets=[];page.on('request',request=>{if(request.method()==='PUT')offsets.push(Number(request.headers()['upload-offset']));});
  await page.locator('#picker').setInputFiles(file);
  await page.getByText('已送达 · SHA-256 校验通过',{exact:false}).waitFor({timeout:30000});
  assert.deepEqual(offsets,[chunk,chunk*2]);
  assert.equal(hash(await fs.readFile(path.join(folder,'incoming','resume.bin'))),hash(data));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await fs.mkdir(path.join(root,'.tmp'),{recursive:true});
  await page.screenshot({path:path.join(root,'.tmp','resume-mobile.png'),fullPage:true});
  await page.getByRole('button',{name:'移除记录',exact:true}).click();
  await page.locator('.upload-task').waitFor({state:'detached'});
  assert.equal(hash(await fs.readFile(path.join(folder,'incoming','resume.bin'))),hash(data));
  console.log('Browser: pause, reload, server restart, token rotation, reselect, prefix verification, mobile layout, completion and receipt removal passed.');

  // Lose a response AFTER commit: next attempt must query offset instead of duplicating data.
  const retryFile=path.join(folder,'retry.bin');await fs.writeFile(retryFile,data);
  let dropped=false;const retryOffsets=[];
  await page.route('**/api/uploads/*',async route=>{
    if(route.request().method()==='PUT'){
      retryOffsets.push(Number(route.request().headers()['upload-offset']));
      if(!dropped){dropped=true;await route.fetch();await route.abort();return;}
    }
    await route.continue();
  });
  await page.locator('#picker').setInputFiles(retryFile);
  await page.getByText('已送达 · SHA-256 校验通过',{exact:false}).waitFor({timeout:30000});
  assert.deepEqual(retryOffsets,[0,chunk,chunk*2]);
  assert.equal(hash(await fs.readFile(path.join(folder,'incoming','retry.bin'))),hash(data));
  await page.unrouteAll({behavior:'wait'});
  console.log('Browser: committed-but-lost response automatically resumes without retransmitting acknowledged chunks.');
  await page.getByRole('button',{name:'移除记录',exact:true}).click();
  await page.locator('.upload-task').waitFor({state:'detached'});

  // Same metadata and sampled edges, but different uploaded interior: never splice it.
  const changedFile=path.join(folder,'changed.bin'), fixedTime=new Date(1700000000000);
  await fs.writeFile(changedFile,data);await fs.utimes(changedFile,fixedTime,fixedTime);
  let heldResolve;const held=new Promise(resolve=>heldResolve=resolve);
  await page.route('**/api/uploads/*',async route=>{
    if(route.request().method()==='PUT'&&Number(route.request().headers()['upload-offset'])>=chunk){
      heldResolve();await new Promise(resolve=>setTimeout(resolve,500));await route.abort().catch(()=>{});return;
    }
    await route.continue();
  });
  await page.locator('#picker').setInputFiles(changedFile);await held;
  await page.getByRole('button',{name:'暂停',exact:true}).click();
  await page.getByRole('button',{name:'继续',exact:true}).waitFor();
  await page.unrouteAll({behavior:'wait'});
  const modified=Buffer.from(data);modified[128*1024]^=255;
  await fs.writeFile(changedFile,modified);await fs.utimes(changedFile,fixedTime,fixedTime);
  await open(page);await page.getByRole('button',{name:'选择原文件续传',exact:true}).waitFor();
  await page.locator('#picker').setInputFiles(changedFile);
  await page.getByText('所选文件与已保存内容不同',{exact:false}).waitFor({timeout:20000});
  sessions=(await (await api('')).json()).uploads;
  assert.equal(sessions.length,1);assert.equal(sessions[0].offset,chunk);
  await page.getByRole('button',{name:'取消任务',exact:true}).click();
  await page.locator('.upload-task').waitFor({state:'detached'});
  assert.equal((await (await api('')).json()).uploads.length,0);
  assert.deepEqual(await fs.readdir(path.join(folder,'incoming','.windbridge-partials')),[]);
  console.log('Browser: mismatched uploaded prefix rejected; cancellation removes partial data.');

  const zero=path.join(folder,'empty.bin'), small=path.join(folder,'small.bin');
  await fs.writeFile(zero,Buffer.alloc(0));await fs.writeFile(small,Buffer.from('queue'));
  await page.locator('#picker').setInputFiles([zero,small]);
  await page.waitForFunction(()=>document.querySelectorAll('.upload-task progress').length===2&&
    [...document.querySelectorAll('.upload-task .meta')].every(el=>el.textContent.includes('已送达')));
  assert.equal((await fs.stat(path.join(folder,'incoming','empty.bin'))).size,0);
  assert.equal(await fs.readFile(path.join(folder,'incoming','small.bin'),'utf8'),'queue');
  console.log('Browser: multi-file queue and zero-byte upload passed.');
  assert.deepEqual(errors,[]);
}
main().catch(error=>{console.error(error.message);process.exitCode=1;}).finally(async()=>{
  await browser?.close();await stop();
  // Only remove the isolated temporary directory created by this test.
  if(folder&&path.dirname(path.resolve(folder))===path.resolve(os.tmpdir())&&path.basename(folder).startsWith('windbridge-browser-'))
    await fs.rm(folder,{recursive:true,force:true});
});
