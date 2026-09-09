async page => {
  const names = Array.from({length:12}, (_,i)=>`post-${String(i+1).padStart(2,'0')}`).concat([1,2,3].flatMap(i=>[`cover-${i}-desktop`,`cover-${i}-mobile`]));
  const failures=[];
  for(const name of names){
    await page.goto(`http://127.0.0.1:5181/${name}.svg`);
    const size=await page.locator('svg').evaluate(svg=>({width:svg.viewBox.baseVal.width,height:svg.viewBox.baseVal.height}));
    await page.setViewportSize(size);
    const clipped=await page.locator('svg').evaluate(svg=>Array.from(svg.querySelectorAll('text')).filter(t=>{const b=t.getBBox();return b.x<0||b.y<0||b.x+b.width>svg.viewBox.baseVal.width||b.y+b.height>svg.viewBox.baseVal.height}).map(t=>t.textContent));
    if(clipped.length) failures.push({name,clipped});
    await page.locator('svg').screenshot({path:`docs/marketing/vk-design/${name}.png`});
  }
  if(failures.length)throw new Error(JSON.stringify(failures));
  return {images:names.length,clippedText:0};
}
