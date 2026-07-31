import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Carrega o .env do projeto (raiz do descontos.bot) para dentro de process.env, para
// o adapter subir sozinho com `npm start` sem depender de variáveis exportadas na shell.
// O caminho é relativo a ESTE arquivo (não ao cwd), então funciona de qualquer diretório.
// Variáveis já presentes no ambiente têm precedência; se o .env não existir, segue em frente.
const here = path.dirname(fileURLToPath(import.meta.url));
const envPath = path.join(here, '..', '..', '.env');

try {
  process.loadEnvFile(envPath);
} catch (error) {
  console.warn(`[evolution_adapter] .env não carregado (${envPath}): ${error.message}`);
}
