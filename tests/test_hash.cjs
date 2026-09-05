const assert = require('node:assert/strict');
const {createHash, randomBytes} = require('node:crypto');
const {fallback, digest} = require('../web/sha256.js');
(async()=>{
  for(const size of [0,1,3,55,56,63,64,65,1000,65536,4*1024*1024]){
    const bytes=randomBytes(size), expected=createHash('sha256').update(bytes).digest('hex');
    assert.equal(fallback(bytes),expected);
    assert.equal(await digest(bytes),expected);
  }
  console.log('SHA-256: 11 sizes passed (fallback + Web Crypto)');
})().catch(error=>{console.error(error);process.exitCode=1;});
