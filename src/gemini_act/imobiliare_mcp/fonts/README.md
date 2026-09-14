# Fonturi încorporate

Familia **Roboto** (Apache License 2.0 — vezi `LICENSE.txt`), folosită de
`generator_pdf.py`.

Fonturile PDF standard sunt Type1 cu codare WinAnsi (Latin-1), care nu conține
`ă` (U+0103), `ș` (U+0219) și `ț` (U+021B) — cu ele, fiecare titlu și celulă de
tabel din raport se desena cu pătrate negre în locul diacriticelor.

Fișierele sunt livrate în pachet, nu căutate în sistem: imaginea de deploy este
`python:3.12-slim`, care nu are niciun font instalat.
