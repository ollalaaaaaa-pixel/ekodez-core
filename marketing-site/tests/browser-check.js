async page => {
  await page.goto('http://127.0.0.1:5180/?utm_source=vk');
  const quizHref = await page.getByRole('link', {name:'Обсудить задачу →', exact:true}).first().getAttribute('href');
  if (!quizHref.includes('utm_source=vk')) throw new Error('Attribution lost between landing and quiz');
  await page.goto('http://127.0.0.1:5180/quiz?utm_source=vk');
  await page.getByRole('button', {name:'Далее →', exact:true}).click();
  if (!await page.getByRole('alert').getByText('Выберите ответ.').isVisible()) throw new Error('Empty step not blocked');
  await page.getByRole('button', {name:'Клопы', exact:true}).click();
  await page.getByRole('button', {name:'Далее →', exact:true}).click();
  await page.getByRole('button', {name:'Квартира', exact:true}).click();
  await page.getByRole('button', {name:'Далее →', exact:true}).click();
  await page.getByLabel('Квадратные метры').fill('0');
  await page.getByRole('button', {name:'Далее →', exact:true}).click();
  if (!await page.getByRole('alert').getByText('Введите площадь больше нуля', {exact:false}).isVisible()) throw new Error('Zero area not blocked');
  await page.getByLabel('Квадратные метры').fill('45');
  await page.getByRole('button', {name:'Далее →', exact:true}).click();
  await page.getByRole('button', {name:'На этой неделе', exact:true}).click();
  await page.getByRole('button', {name:'Далее →', exact:true}).click();
  await page.getByRole('button', {name:'Напишу в Telegram', exact:true}).click();
  await page.getByRole('button', {name:'Далее →', exact:true}).click();
  if (!await page.getByText('Заявка ещё не отправлена.',{exact:false}).isVisible()) throw new Error('False submission claim');
  const href=await page.getByRole('link',{name:'Открыть Telegram',exact:true}).getAttribute('href');
  if(href!=='https://t.me/ekodez_bot?start=m_vk') throw new Error('Unsafe attribution link');
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  if(overflow) throw new Error('Mobile horizontal overflow');
  await page.screenshot({path:'marketing-site/quiz-mobile.png',fullPage:true});
  return {steps:5,emptyBlocked:true,zeroBlocked:true,telegramHref:href,horizontalOverflow:false,externalMessagesSent:0};
}
