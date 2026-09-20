// three.js, servi depuis notre propre domaine.
//
// Le document « Noyau » est un fichier HTML autonome, écrit avec un <script> classique et
// un `THREE` global — il attendait three.js depuis cdnjs. Deux raisons de ne pas laisser
// faire : la politique de sécurité de l'application n'autorise aucun script tiers, et la
// politique de confidentialité promet qu'aucune ressource extérieure n'est chargée.
//
// Ce fichier transforme le paquet npm `three` (déjà déclaré dans web/package.json, donc
// verrouillé et vérifié comme les autres) en un bundle classique qui pose `window.THREE`.
//
//   node web/vendor-src/construire.mjs      (ou : npm run vendoriser --workspace web)
import * as THREE from "three";
window.THREE = THREE;
