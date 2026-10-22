import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire('C:/Users/A/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/package.json');
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
for(const name of ['task_spectrum_template','task_spectrum_30day_example']) {
  const dir='E:/15_project/data/degradation/r2';
  const matrix=JSON.parse(await fs.readFile(`${dir}/${name}.json`,'utf8'));
  const wb=Workbook.create(); const sh=wb.worksheets.add('任务载荷谱');
  sh.showGridLines=false;
  const range=sh.getRangeByIndexes(0,0,matrix.length,16);
  range.values=matrix;
  range.format.font={name:'Microsoft YaHei',size:11};
  range.format.columnWidth=22; range.format.rowHeight=24;
  sh.getRange('A1:P1').format={fill:'#245f91',font:{bold:true,color:'#ffffff'},wrapText:true,rowHeight:46};
  sh.freezePanes.freezeRows(1);
  sh.getRange('P2:P332').dataValidation={rule:{type:'decimal',operator:'greaterThan',formula1:0}};
  sh.getRange('P2:P332').format.fill='#fff2cc';
  if(matrix.length>1) sh.tables.add(`A1:P${matrix.length}`,true,'MissionSegments');
  wb.recalculate();
  console.log((await wb.inspect({kind:'table',range:'任务载荷谱!A1:D4',tableMaxRows:4,tableMaxCols:4,maxChars:1200})).ndjson);
  await (await SpreadsheetFile.exportXlsx(wb)).save(`${dir}/${name}.xlsx`);
  try {
    const preview=await wb.render({sheetName:'任务载荷谱',range:'A1:F8',scale:1.5});
    await fs.writeFile(`${dir}/${name}_preview.png`,new Uint8Array(await preview.arrayBuffer()));
  } catch(error) { console.log('RENDER_LIMITATION',String(error)); }
}
