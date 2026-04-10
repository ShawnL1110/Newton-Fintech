/**
 * OnePrestamos Blog - Articles Data
 * ===================================
 * To add a new article:
 * 1. Create a new HTML file in /articles/ folder
 * 2. Add an entry to the ARTICLES array below
 * 3. The blog listing page will automatically pick it up
 *
 * Categories: "educacion-financiera", "guia-prestamos", "seguridad-confianza"
 */

const ARTICLES = [
  {
    id: "que-es-prestamo-rapido",
    title: "¿Qué es un préstamo rápido y cómo funciona?",
    excerpt: "Descubre qué son los préstamos rápidos online, cómo funcionan, qué requisitos necesitas y qué debes tener en cuenta antes de solicitar uno en España.",
    category: "educacion-financiera",
    categoryLabel: "Educación Financiera",
    date: "2026-04-08",
    readTime: "6 min",
    image: "assets/prestamo-rapido.svg",
    url: "articles/que-es-prestamo-rapido.html",
    keywords: ["préstamo rápido", "micropréstamo", "crédito online", "qué es un préstamo rápido"],
    author: "One Prestamos"
  },
  {
    id: "como-solicitar-prestamo-online",
    title: "Cómo solicitar un préstamo online en España: guía paso a paso",
    excerpt: "Te explicamos el proceso completo para solicitar un préstamo online en España: desde los requisitos hasta la recepción del dinero en tu cuenta bancaria.",
    category: "guia-prestamos",
    categoryLabel: "Guía de Préstamos",
    date: "2026-04-05",
    readTime: "7 min",
    image: "assets/solicitar-prestamo.svg",
    url: "articles/como-solicitar-prestamo-online.html",
    keywords: ["solicitar préstamo online", "préstamo online España", "cómo pedir un préstamo"],
    author: "One Prestamos"
  },
  {
    id: "prestamos-online-seguros",
    title: "¿Son seguros los préstamos online? Claves para identificar empresas fiables",
    excerpt: "Aprende a distinguir las empresas de préstamos online legítimas de las fraudulentas. Conoce las certificaciones AEMIP y las señales de confianza.",
    category: "seguridad-confianza",
    categoryLabel: "Seguridad y Confianza",
    date: "2026-04-01",
    readTime: "5 min",
    image: "assets/prestamos-seguros.svg",
    url: "articles/prestamos-online-seguros.html",
    keywords: ["préstamos online seguros", "préstamos fiables", "AEMIP", "seguridad préstamos"],
    author: "One Prestamos"
  }
];

// Category configuration
const CATEGORIES = {
  "all": { label: "Todos", color: "#E8604C" },
  "educacion-financiera": { label: "Educación Financiera", color: "#E8604C" },
  "guia-prestamos": { label: "Guía de Préstamos", color: "#F4845F" },
  "seguridad-confianza": { label: "Seguridad y Confianza", color: "#D4503E" }
};

// Helper: format date to Spanish
function formatDateES(dateStr) {
  const months = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"];
  const d = new Date(dateStr + "T00:00:00");
  return `${d.getDate()} de ${months[d.getMonth()]} de ${d.getFullYear()}`;
}

// Export for use in both listing and article pages
if (typeof module !== 'undefined') module.exports = { ARTICLES, CATEGORIES, formatDateES };
