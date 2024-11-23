import { google } from 'googleapis';
import fetch from 'node-fetch';

const SCOPES = ['https://www.googleapis.com/auth/spreadsheets'];
const SPREADSHEET_ID = process.env.SPREADSHEET_ID;
const PERPLEXITY_API_KEY = process.env.PERPLEXITY_API_KEY;

async function setupSheets() {
  const auth = new google.auth.GoogleAuth({
    scopes: SCOPES,
  });
  const client = await auth.getClient();
  return google.sheets({ version: 'v4', auth: client });
}

async function getUnprocessedArticles(sheets) {
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: 'Articles!A2:D',
  });
  const rows = response.data.values || [];
  return rows.filter(row => row[1] === "Неопубліковано");
}

async function analyzeWithPerplexity(title, content) {
  const prompt = `Проаналізуйте цю новину та визначте, чи вона стосується України. Заголовок: '${title}'. Зміст: '${content.slice(0, 500)}...'. Дайте відповідь 'Так' або 'Ні', а потім оцініть актуальність новини для України за шкалою від 1 до 10.`;
  
  const response = await fetch("https://api.perplexity.ai/chat/completions", {
    method: 'POST',
    headers: {
      "Authorization": `Bearer ${PERPLEXITY_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: "mixtral-8x7b-instruct",
      messages: [{ role: "user", content: prompt }]
    })
  });

  const result = await response.json();
  const analysis = result.choices[0].message.content;
  
  const isRelevant = analysis.split()[0].includes("Так");
  const relevanceScore = isRelevant ? parseInt(analysis.split().pop()) : 0;
  
  return { isRelevant, relevanceScore };
}

async function updateArticleStatus(sheets, row, status, facebook = false) {
  const range = `Articles!B${row}:E${row}`;
  const values = [[status, null, null, facebook ? "Facebook" : null]];
  
  await sheets.spreadsheets.values.update({
    spreadsheetId: SPREADSHEET_ID,
    range: range,
    valueInputOption: 'USER_ENTERED',
    resource: { values },
  });
}

export default async function handler(req, res) {
  try {
    const sheets = await setupSheets();
    const articles = await getUnprocessedArticles(sheets);
    
    let processedCount = 0;
    for (const [index, article] of articles.entries()) {
      const [title, , , content] = article;
      const { isRelevant, relevanceScore } = await analyzeWithPerplexity(title, content);
      
      if (!isRelevant) {
        await updateArticleStatus(sheets, index + 2, "Забраковано");
      } else if (relevanceScore >= 8) {
        await updateArticleStatus(sheets, index + 2, "Опубліковано", true);
      } else {
        await updateArticleStatus(sheets, index + 2, "Опубліковано");
      }
      processedCount++;
    }
    
    res.status(200).json({ message: `Успішно оброблено ${processedCount} статей.` });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'An error occurred while processing articles', details: error.message });
  }
}