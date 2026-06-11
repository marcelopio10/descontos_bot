const fs = require('fs');
const path = require('path');
const sharp = require('../site/node_modules/sharp');

const width = 1080;
const height = 1920;

const colors = {
  background: '#0D0F14',
  cyan: '#00C9B1',
  yellow: '#FFE14D',
  darkGray: '#1E2330',
  altGray: '#161A22',
  white: '#F7FAFC',
  muted: '#A5B1C2',
  whatsapp: '#25D366',
};

const outputPath = path.join(__dirname, 'story-whatsapp-codex.png');

const escapeXml = (value) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

const createSvgOverlay = (content) =>
  Buffer.from(
    `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" fill="none" xmlns="http://www.w3.org/2000/svg">${content}</svg>`
  );

const baseOverlay = createSvgOverlay(`
  <defs>
    <linearGradient id="bgGlow" x1="140" y1="80" x2="940" y2="1760" gradientUnits="userSpaceOnUse">
      <stop stop-color="${colors.altGray}" />
      <stop offset="1" stop-color="${colors.background}" />
    </linearGradient>
    <radialGradient id="cyanBloom" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(915 180) rotate(123.51) scale(533 424)">
      <stop stop-color="${colors.cyan}" stop-opacity="0.30" />
      <stop offset="1" stop-color="${colors.cyan}" stop-opacity="0" />
    </radialGradient>
    <radialGradient id="yellowBloom" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(200 1620) rotate(32.4) scale(485 390)">
      <stop stop-color="${colors.yellow}" stop-opacity="0.16" />
      <stop offset="1" stop-color="${colors.yellow}" stop-opacity="0" />
    </radialGradient>
    <linearGradient id="panelStroke" x1="250" y1="600" x2="860" y2="1470" gradientUnits="userSpaceOnUse">
      <stop stop-color="${colors.cyan}" stop-opacity="0.45" />
      <stop offset="1" stop-color="${colors.yellow}" stop-opacity="0.20" />
    </linearGradient>
    <linearGradient id="ctaFill" x1="110" y1="0" x2="970" y2="0" gradientUnits="userSpaceOnUse">
      <stop stop-color="${colors.whatsapp}" />
      <stop offset="1" stop-color="#41E07E" />
    </linearGradient>
    <filter id="softBlur">
      <feGaussianBlur stdDeviation="18" />
    </filter>
  </defs>

  <rect width="${width}" height="${height}" fill="${colors.background}" />
  <rect width="${width}" height="${height}" fill="url(#bgGlow)" />
  <circle cx="915" cy="180" r="533" fill="url(#cyanBloom)" />
  <circle cx="190" cy="1640" r="420" fill="url(#yellowBloom)" />

  <g opacity="0.14">
    <path d="M0 260H1080" stroke="${colors.cyan}" stroke-width="2" stroke-dasharray="10 18" />
    <path d="M0 1460H1080" stroke="${colors.yellow}" stroke-width="2" stroke-dasharray="10 18" />
    <path d="M780 0V1920" stroke="${colors.cyan}" stroke-width="1.5" stroke-dasharray="8 20" />
    <path d="M160 0V1920" stroke="${colors.yellow}" stroke-width="1.5" stroke-dasharray="8 20" />
  </g>

  <rect x="64" y="58" width="952" height="1804" rx="42" fill="${colors.altGray}" fill-opacity="0.52" stroke="url(#panelStroke)" stroke-opacity="0.40" />

  <g opacity="0.9">
    <circle cx="135" cy="155" r="6" fill="${colors.cyan}" />
    <circle cx="158" cy="155" r="6" fill="${colors.yellow}" />
    <circle cx="181" cy="155" r="6" fill="${colors.whatsapp}" />
  </g>

  <rect x="102" y="112" width="255" height="46" rx="23" fill="${colors.darkGray}" />
  <text x="132" y="142" fill="${colors.cyan}" font-family="'Courier New', monospace" font-size="22" font-weight="700" letter-spacing="3">DESCONTOS.BOT</text>

  <g transform="translate(846 116)">
    <rect width="132" height="44" rx="22" fill="${colors.darkGray}" />
    <text x="66" y="29" text-anchor="middle" fill="${colors.yellow}" font-family="Arial, sans-serif" font-size="20" font-weight="700">24/7</text>
  </g>

  <g opacity="0.95">
    <path d="M902 237C960 223 1011 263 1015 323C1019 383 984 439 929 450C874 461 837 420 816 370C792 313 844 250 902 237Z" fill="${colors.cyan}" fill-opacity="0.10" stroke="${colors.cyan}" stroke-opacity="0.35"/>
    <path d="M165 440C246 397 347 420 389 500C431 580 395 669 317 705C239 741 151 710 110 641C69 572 84 484 165 440Z" fill="${colors.yellow}" fill-opacity="0.08" stroke="${colors.yellow}" stroke-opacity="0.30"/>
  </g>

  <g filter="url(#softBlur)" opacity="0.55">
    <rect x="112" y="1125" width="856" height="140" rx="70" fill="${colors.whatsapp}" fill-opacity="0.18" />
  </g>
`);

const textOverlay = createSvgOverlay(`
  <text x="108" y="252" fill="${colors.yellow}" font-family="'Courier New', monospace" font-size="28" font-weight="700" letter-spacing="4">ALERTA DE OFERTAS</text>

  <text x="108" y="360" fill="${colors.white}" font-family="Arial, sans-serif" font-size="70" font-weight="800">
    <tspan x="108" dy="0">O bot nunca dorme.</tspan>
    <tspan x="108" dy="84">Você nunca paga caro.</tspan>
  </text>

  <text x="108" y="584" fill="${colors.muted}" font-family="Arial, sans-serif" font-size="34" font-weight="400">
    <tspan x="108" dy="0">Grupo WhatsApp gratuito com alertas em tempo real</tspan>
    <tspan x="108" dy="46">das melhores ofertas</tspan>
  </text>

  <text x="108" y="1688" fill="${colors.white}" font-family="'Courier New', monospace" font-size="34" font-weight="700">@descontos.bot</text>
  <text x="108" y="1750" fill="${colors.muted}" font-family="Arial, sans-serif" font-size="22" font-weight="400">https://chat.whatsapp.com/EKf4vnNG8MdLurY9xKrqAm</text>
`);

const benefitCards = [
  {
    x: 108,
    title: 'Tempo real',
    accent: colors.cyan,
    body: 'Alertas assim que\nas ofertas aparecem',
  },
  {
    x: 378,
    title: 'Curadoria',
    accent: colors.yellow,
    body: 'Só entra o que\nvale a pena abrir',
  },
  {
    x: 648,
    title: 'Grátis',
    accent: colors.whatsapp,
    body: 'Acesso livre para\nreceber e economizar',
  },
];

const cardsOverlay = createSvgOverlay(
  benefitCards
    .map(
      (card) => `
        <g transform="translate(${card.x} 770)">
          <rect width="228" height="260" rx="30" fill="${colors.darkGray}" stroke="${card.accent}" stroke-opacity="0.38" />
          <rect x="24" y="26" width="58" height="10" rx="5" fill="${card.accent}" />
          <text x="24" y="96" fill="${colors.white}" font-family="Arial, sans-serif" font-size="38" font-weight="800">${escapeXml(card.title)}</text>
          <text x="24" y="150" fill="${colors.muted}" font-family="Arial, sans-serif" font-size="28" font-weight="400">
            ${card.body
              .split('\n')
              .map((line, index) => `<tspan x="24" dy="${index === 0 ? 0 : 38}">${escapeXml(line)}</tspan>`)
              .join('')}
          </text>
        </g>
      `
    )
    .join('')
);

const ctaOverlay = createSvgOverlay(`
  <g transform="translate(108 1140)">
    <rect width="864" height="188" rx="40" fill="url(#ctaFill)" />
    <rect x="8" y="8" width="848" height="172" rx="34" fill="none" stroke="#9AF0B9" stroke-opacity="0.45" />
    <circle cx="108" cy="94" r="44" fill="#F4FFF8" fill-opacity="0.20" />
    <path d="M122.3 110.5C116.6 107.7 105.8 102.6 101 100.5C99.1 99.7 97.7 99.3 96.7 99.3C95.4 99.4 93.5 99.8 92.3 103.1C91.1 106.4 87.8 117.4 87.3 119.1C86.8 120.9 86.5 123 87.8 124.8C89 126.5 92.8 131.3 96.9 136C102.2 142 106.7 146.8 114.5 151.3C122.3 155.8 126.1 156.4 129.2 155.2C132.3 153.9 139.6 147.7 141 144.6C142.5 141.4 142.5 138.6 142.1 137.9C141.6 137.1 140.3 136.7 138.4 135.7C136.5 134.8 127.9 130.6 126.2 129.9C124.5 129.3 123.3 129 122.1 130.8C120.8 132.7 117.4 136.7 116.4 137.9C115.4 139.1 114.3 139.3 112.4 138.4C110.4 137.4 104.2 135.4 97.1 128.9C91.6 123.9 87.9 117.7 86.9 115.8C85.9 113.9 86.8 112.9 87.7 111.9C88.6 111 89.7 109.5 90.7 108.3C91.7 107.1 92 106.3 92.6 105.1C93.2 103.8 92.9 102.7 92.4 101.8C91.9 100.8 87.8 90.7 86 86.5C84.4 82.7 82.8 83.2 81.6 83.1C80.5 83.1 79.2 83.1 77.9 83.1C76.6 83.1 74.6 83.6 72.9 85.4C71.2 87.2 66.3 91.7 66.3 101.1C66.3 110.5 73.1 119.6 74 120.9C74.9 122.2 87.2 141.3 105.9 149.6C124.7 157.9 124.7 155.1 131.4 154.4C138.1 153.8 153.1 148.3 156 140.2C159 132.1 159 125.1 158.1 123.6C157.1 122 154.8 121.1 149.1 118.3C143.5 115.4 127.9 107.7 122.3 110.5Z" fill="#FFFFFF" transform="translate(28 12) scale(0.52)" />
    <text x="206" y="104" fill="#F7FFF9" font-family="Arial, sans-serif" font-size="52" font-weight="800">Entrar no WhatsApp</text>
    <text x="206" y="146" fill="#D5FFE4" font-family="'Courier New', monospace" font-size="24" font-weight="700" letter-spacing="2">OFERTAS EM TEMPO REAL</text>
  </g>

  <g transform="translate(108 1374)">
    <rect width="864" height="220" rx="34" fill="${colors.darkGray}" fill-opacity="0.94" stroke="${colors.cyan}" stroke-opacity="0.22" />
    <text x="42" y="66" fill="${colors.cyan}" font-family="'Courier New', monospace" font-size="24" font-weight="700" letter-spacing="3">ACESSO DIRETO</text>
    <text x="42" y="128" fill="${colors.white}" font-family="Arial, sans-serif" font-size="46" font-weight="800">Link do grupo:</text>
    <text x="42" y="172" fill="${colors.yellow}" font-family="'Courier New', monospace" font-size="20" font-weight="700">${escapeXml('chat.whatsapp.com/EKf4vnNG8MdLurY9xKrqAm')}</text>
  </g>
`);

async function generateStory() {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });

  await sharp({
    create: {
      width,
      height,
      channels: 4,
      background: colors.background,
    },
  })
    .composite([
      { input: baseOverlay },
      { input: textOverlay },
      { input: cardsOverlay },
      { input: ctaOverlay },
    ])
    .png()
    .toFile(outputPath);

  const metadata = await sharp(outputPath).metadata();
  if (metadata.width !== width || metadata.height !== height) {
    throw new Error(`Unexpected output size: ${metadata.width}x${metadata.height}`);
  }

  console.log(`Generated ${outputPath}`);
  console.log(`Verified dimensions: ${metadata.width}x${metadata.height}`);
}

generateStory().catch((error) => {
  console.error(error);
  process.exit(1);
});
