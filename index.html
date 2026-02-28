<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>FC Evolution Local Dashboard</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #0f1115; color: #e0e0e0; padding: 20px; }
        .container { max-width: 1200px; margin: auto; }
        
        /* Search Bar */
        #search { width: 100%; padding: 15px; margin-bottom: 20px; border-radius: 8px; border: 1px solid #3d4451; background: #1a1d23; color: white; font-size: 1rem; box-sizing: border-box;}

        /* Table Styles */
        table { width: 100%; border-collapse: collapse; background: #1a1d23; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        th, td { padding: 15px; border-bottom: 1px solid #2d323a; text-align: left; }
        th { background: #252932; color: #00ffcc; text-transform: uppercase; font-size: 0.85rem; letter-spacing: 1px; }
        tr:hover { background: #22262f; }
        
        /* Image/Icon Styles */
        .icon-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
        .ps-icon { width: 36px; height: 36px; object-fit: contain; border-radius: 4px; background: rgba(0,0,0,0.2); }
        .plus-icon { border: 2px solid #ffcc00; box-shadow: 0 0 8px rgba(255, 204, 0, 0.5); }
        .text-fallback { font-size: 0.8rem; color: #888; font-style: italic; }
    </style>
</head>
<body>

<div class="container">
    <h2>Local Evolution Tracker</h2>
    <input type="text" id="search" placeholder="Search by Evolution Name, or Base/Plus Playstyle..." onkeyup="filterTable()">

    <table id="evoTable">
        <thead>
            <tr>
                <th>Evolution Name</th>
                <th>Playstyles (Base)</th>
                <th>Playstyle+ (Plus)</th>
            </tr>
        </thead>
        <tbody id="tableBody"></tbody>
    </table>
</div>

<script>
    // 1. DATA MAPPING (Matches your text list to local file paths)
    const playstyleMap = {
        "Finesse Shot": { folder: "Finishing", file: "finesse_shot" },
        "Power Shot": { folder: "Finishing", file: "power_shot" },
        "Precision Header": { folder: "Finishing", file: "precision_header" },
        "Low Driven Shot": { folder: "Finishing", file: "low_driven_shot" },
        "Dead Ball": { folder: "Finishing", file: "dead_ball" },
        "Acrobatic": { folder: "Finishing", file: "acrobatic" },
        "Gamechanger": { folder: "Finishing", file: "gamechanger" },
        "Pinged Pass": { folder: "Passing", file: "pinged_pass" },
        "Incisive Pass": { folder: "Passing", file: "incisive_pass" },
        "Whipped Pass": { folder: "Passing", file: "whipped_pass" },
        "Tiki Taka": { folder: "Passing", file: "tiki_taka" },
        "Inventive": { folder: "Passing", file: "inventive" },
        "Anticipate": { folder: "Defending", file: "anticipate" },
        "Intercept": { folder: "Defending", file: "intercept" },
        "Bruiser": { folder: "Physical", file: "bruiser" },
        "Slide Tackle": { folder: "Defending", file: "slide_tackle" },
        "Aerial Fortress": { folder: "Defending", file: "aerial_fortress" },
        "Quick Step": { folder: "Physical", file: "quick_step" },
        "Rapid": { folder: "BallControl", file: "rapid" },
        "Technical": { folder: "BallControl", file: "technical" },
        "Trickster": { folder: "BallControl", file: "trickster" },
        "Relentless": { folder: "Physical", file: "relentless" },
        "First Touch": { folder: "BallControl", file: "first_touch" },
        "Press Proven": { folder: "BallControl", file: "press_proven" },
        "Enforcer": { folder: "Physical", file: "enforcer" }
    };

    // 2. EVOLUTION DATA
    const evolutionData = [
        { name: "Bench Boost", ps: ["Precision Header", "Tiki Taka", "Enforcer", "Acrobatic", "Aerial Fortress"], plus: ["Precision Header"] },
        { name: "Max Skills", ps: ["Quick Step", "Trickster", "Rapid", "Technical"], plus: ["Quick Step", "Trickster"] },
        { name: "Midfield Dynamo", ps: ["Pinged Pass", "Anticipate", "Inventive", "Press Proven"], plus: ["Anticipate"] },
        { name: "Going on an Adventure", ps: ["Intercept", "Dead Ball", "Relentless"], plus: ["Whipped Pass"] },
        { name: "Instant Impact", ps: ["Finesse Shot", "Rapid"], plus: ["Finesse Shot"] },
        { name: "Passing Pro", ps: ["Pinged Pass"], plus: ["Pinged Pass"] },
        { name: "Climb The Ladder", ps: ["Aerial Fortress"], plus: ["Aerial Fortress"] },
        { name: "Fantasy Staple", ps: ["Rapid", "Low Driven Shot", "Finesse Shot", "Enforcer", "Aerial Fortress"], plus: ["Rapid"] },
        { name: "Running Workout", ps: ["Quick Step", "Relentless"], plus: [] },
        { name: "Fantasy FC Path", ps: ["Low Driven Shot", "First Touch", "Finesse Shot", "Power Shot"], plus: ["Low Driven Shot"] },
        { name: "Mindset Training", ps: ["First Touch", "Anticipate", "Relentless", "Pinged Pass"], plus: ["Press Proven"] },
        { name: "Refined Flank Runner", ps: ["Technical", "Finesse Shot", "Rapid", "Incisive Pass"], plus: ["Technical"] },
        { name: "Inside Edge", ps: ["Low Driven Shot", "Gamechanger", "Technical", "Tiki Taka", "Incisive Pass"], plus: ["Finesse Shot"] },
        { name: "Iconic Attacker Glow Up", ps: ["Finesse Shot", "Rapid", "Incisive Pass", "Power Shot"], plus: ["Low Driven Shot", "Gamechanger"] },
        { name: "Iconic Defender Glow Up", ps: ["Intercept", "Anticipate", "Tiki Taka", "Bruiser", "Slide Tackle"], plus: ["Intercept"] }
    ];

    function renderTable() {
        const tableBody = document.getElementById('tableBody');
        evolutionData.forEach(evo => {
            const row = document.createElement('tr');
            
            // Build base playstyles HTML
            const baseHTML = evo.ps.map(p => {
                const data = playstyleMap[p];
                if (data) {
                    return `<img src="${data.folder}/${data.file}_standard.png" class="ps-icon" title="${p} Base">`;
                }
                return `<span class="text-fallback">${p}</span>`;
            }).join('');

            // Build plus playstyles HTML
            const plusHTML = evo.plus.map(p => {
                const data = playstyleMap[p];
                if (data) {
                    return `<img src="${data.folder}/${data.file}_plus.png" class="ps-icon plus-icon" title="${p} Plus">`;
                }
                return `<span class="text-fallback">${p}</span>`;
            }).join('');

            row.innerHTML = `
                <td><strong>${evo.name}</strong></td>
                <td><div class="icon-row">${baseHTML}</div></td>
                <td><div class="icon-row">${plusHTML}</div></td>
            `;
            tableBody.appendChild(row);
        });
    }

    function filterTable() {
        const query = document.getElementById('search').value.toLowerCase();
        const rows = document.getElementById('tableBody').getElementsByTagName('tr');
        
        for (let row of rows) {
            const evoName = row.cells[0].innerText.toLowerCase();
            
            // Get titles from images for playstyle names
            const baseImages = row.cells[1].querySelectorAll('img');
            const plusImages = row.cells[2].querySelectorAll('img');
            
            let match = false;
            if (evoName.includes(query)) match = true;
            
            // Check Base Images
            baseImages.forEach(img => {
                if (img.title.toLowerCase().includes(query)) match = true;
            });
            
            // Check Plus Images
            plusImages.forEach(img => {
                if (img.title.toLowerCase().includes(query)) match = true;
            });
            
            // Handle shorthand 'plus' searching (e.g. "rapid+" matches "rapid plus")
            if (query.endsWith('+') || query.endsWith('plus')) {
                const searchTerm = query.replace('+', '').replace('plus', '').trim();
                plusImages.forEach(img => {
                    if (img.title.toLowerCase().includes(searchTerm)) match = true;
                });
            }
            
            row.style.display = match ? "" : "none";
        }
    }

    renderTable();
</script>

</body>
</html>
