# UMA SEO AI Agent (flat version, phone ke liye)

Saari files ek hi jagah (root) hain. Sirf 2 workflow files `.github/workflows/` mein GitHub par "Create new file" se banani hain (chat mein code diya hai).

Pages: Settings > Pages > Branch main, folder **/ (root)**.
Secret: `GEMINI_API_KEY` (free: aistudio.google.com/apikey), optional `PSI_KEY`.
Actions > Workflow permissions > Read and write.
Phir Actions > UMA SEO AI Agent > Run workflow.

Apni doosri sites config.json ke `sites_to_audit` mein daal sakte ho.
Competitor ka search volume aur backlinks free mein nahi milte, is liye nahi hain.
Articles AI likhta hai aur seedha publish hote hain; pehle dekhna ho to config.json mein `"publish_articles": false` kar do.
