// Optional real-network arXiv UI gate; no extension/translation calls.
import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
const origin=process.argv[2]||'http://127.0.0.1:8010';
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 await page.goto(origin+'/');
 await page.getByRole('button',{name:'Add Paper',exact:true}).click();
 await page.getByRole('button',{name:'arXiv Link',exact:true}).click();
 await page.getByPlaceholder('https://arxiv.org/abs/1706.03762').fill('2402.08954');
 await page.getByRole('button',{name:'导入 arXiv',exact:true}).click();
 await page.getByRole('status').waitFor();
 await page.getByRole('button',{name:'关闭',exact:true}).click();
 const link=page.locator('a[href="https://arxiv.org/html/2402.08954"]').first();
 await link.waitFor({timeout:60000});
 const [external]=await Promise.all([page.waitForEvent('popup'),link.click()]);
 const response=await external.waitForLoadState('domcontentloaded').then(()=>external.url());
 if(!response.startsWith('https://arxiv.org/html/2402.08954'))throw new Error('Unexpected official page destination');
 await external.close();
 await page.reload();await page.waitForSelector('.paper-row');
 const list=await page.evaluate(async()=>{const r=await fetch('/api/v1/papers?q=2402.08954');return r.json();});
 const paper=list.items[0];
 if(!paper||paper.metadata_status!=='ready'||paper.read_status!=='reading'||!paper.last_read_at)throw new Error('Official HTML state did not persist');
 const result={input:'2402.08954',metadata:'PASS',official_html:'PASS',new_tab:'PASS',last_read_at:'PASS',external_scroll_tracking:false,read_frog:'NOT RUN'};
 await page.screenshot({path:'docs/validation/library-arxiv-real.png'});
 fs.writeFileSync('docs/validation/arxiv-browser.json',JSON.stringify(result,null,2)+'\n');
 console.log(result);
}finally{await browser.close();}
