'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function navigation(search = '') {
  const context = {
    window:{}, URL, URLSearchParams,
    location:{origin:'http://127.0.0.1:3199',pathname:'/tasks',search,hash:''},
    document:{querySelector: selector => selector === '.studio' ? {} : null, createElement:()=>({})}
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../assets/mail-web/workspace-shell.js'),'utf8'),context);
  return context.window.OksNavigation;
}
test('return links stay inside this workspace, reject external destinations and remove nested origins',()=>{
  const nav=navigation();
  for(const url of ['https://evil.example','//evil.example','/\\evil.example','javascript:alert(1)',null])assert.equal(nav.localPath(url),null);
  assert.equal(nav.localPath('/start?return_to=%2Ftasks'),'/start');
  assert.equal(nav.localPath('/tasks?id=abc&q=report&return_to=%2Freview'),'/tasks?id=abc&q=report');
});
test('a review or communication link retains the exact selected task and list query',()=>{
  const nav=navigation('?id=task-one&q=report&filter=all&artifact=reports%2Fout.md&artifact_revision=2');
  const review=new URL(nav.fromTask('/review?draft=drafts/a.md&revision=abc'),'http://127.0.0.1:3199');
  assert.equal(review.searchParams.get('revision'),'abc');
  assert.equal(review.searchParams.get('return_to'),nav.here());
  const message=new URL(nav.fromTask('/#collaboration&thread=thread-one'),'http://127.0.0.1:3199');
  assert.equal(message.hash,'#collaboration&thread=thread-one');
  assert.equal(message.searchParams.get('return_to'),nav.here());
});
