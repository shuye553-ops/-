// Run only against work/fmod-reference/sounds.fspro, never a production project.
var banks = studio.project.model.Bank.findInstances();
var bank = null;
for (var i = 0; i < banks.length; i++) {
    if (String(banks[i].name) === "voice_additions") {
        bank = banks[i];
        break;
    }
}
if (!bank) {
    throw new Error("voice_additions is absent from the loaded project model");
}
var bankPath = String(bank.getPath());
console.log("VOICE_BANK_PATH=" + bankPath);
var candidates = [String(bank.name), bankPath.replace(/^bank:\//, ""), bankPath];
var built = false;
for (var j = 0; j < candidates.length && !built; j++) {
    console.log("VOICE_BANK_BUILD_NAME=" + candidates[j]);
    built = studio.project.build({banks: candidates[j], platforms: "Desktop"});
}
console.log("VOICE_BANK_BUILD_SUCCESS=" + built);
if (!built) {
    throw new Error("Native FMOD voice bank build failed");
}
