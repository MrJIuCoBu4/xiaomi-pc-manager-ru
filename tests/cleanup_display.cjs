// The public helper must translate known presentation labels and preserve unknown values.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..'),context={};
vm.runInNewContext(fs.readFileSync(path.join(root,'tools/cleanup_display.js'),'utf8'),context);
const labels=JSON.parse(fs.readFileSync(path.join(root,'translations/cleanup-labels.json'),'utf8'));
for(const [input,output]of Object.entries(labels))assert.equal(context.xprCleanupLabel(input),output);
for(const value of ['Custom app','未知软件','toString','__proto__',null,undefined,123])assert.equal(context.xprCleanupLabel(value),value);
console.log('PASS: cleanup display labels and unknown-name fallback');
