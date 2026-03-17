
const fs = require('fs');
const path = require('path');
const os = require('os');

const TOKEN_FILE_PATH = path.join(os.tmpdir(), 'token.json');
console.log("Token Path:", TOKEN_FILE_PATH);

if (fs.existsSync(TOKEN_FILE_PATH)) {
    fs.unlinkSync(TOKEN_FILE_PATH);
    console.log("Token file deleted.");
} else {
    console.log("Token file not found.");
}
