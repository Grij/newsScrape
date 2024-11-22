import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

export default async function handler(req, res) {
  try {
    const { stdout, stderr } = await execAsync('python rate_articles.py');
    console.log(stdout);
    console.error(stderr);
    res.status(200).json({ message: 'Articles processed successfully' });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'An error occurred while processing articles' });
  }
}
