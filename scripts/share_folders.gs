/**
 * Google Apps Script to share all developer folders with realtor bot
 * Run this in Google Apps Script editor
 */

function shareAllDeveloperFolders() {
  // Email to grant access to
  const BOT_EMAIL = 'davidyaneleonora@gmail.com';
  
  // Known folder IDs from Sofia's links
  const FOLDER_IDS = [
    '1zstD8eqbp6S_k-Dc-0ptlSF_etd_WNY8',
    '1uY91KJWgeAA-pu4weJddDwb54lgeKErJ',
    '113AVp3HKbSoFsWSIJy7lWo8zAujW43xj',
    '1aEpqun0RP1CVHJAuqY6zVYD61dpne3Hs',
    '1oGf7Tpzwx8maeOC2fYpgMUa4mWCc7NNW',
    '1WclbriQ94rCZE0HifntHjBN9yRC1kDgZ',
    '19Ar9IPGcqIE4Hq_PbcTm1W-VsbJpILRJ',
    '1SK7zwecjiQyxkuOLxaaNb4-wxP5VI79K',
    '1EPoCy2iRcx7NlIOqGNuRBzDVPP78H28Q',
    '1jPwCi4aFHlovg0kGQW9PqlUe0ShKQZDI',
    '1hXaNtexBCbHCsUkWgccTHHjY-VMQhgih',
    '1ICAQMI-UkczWmedBJ_mfJgZTP3y6f-Fg',
    '1P9b-mWU_L7JYM11oSh6-E03TYSH0R66c',
    '1p6khe4xJHlCUQ09u71rtiXYHLhmCGG_t',
    '1nob2uyakornEPcPvFtr1wCS6PCnfbxZz',
    '136agYFd6GGSY_wBp6oCoelETPYAMI0fS',
    '1TGV31gooF_X5oXf6bJ3tTY-k2WUu021q',
    '1IyrfCy85bhtx4LyvlIDQg1lr-pKzTjJv',
    '139ihZjdrb3gATeHTd0kWxYTxlMcIdtPh',
    '1Qwt7ndpGQLpcrx4nbNZRp9G7MLcyqSpP',
    '1Lkw5Mm0heDC7d38Ue4j4jKDJ72Nrqo2h',
    '1W7wNgibPMUthBCKKG0zFoEZYM2ukSTRm',
    '182TZDGs6DVWdyo6nmpI_kXGDw3ktEH6M',
    '1plvAPco_mlEIp99qtcFW9woTkOlpAARh',
    '1H3youmf1wApvqn8fnKWl5MrjFzwRWJuL',
    '1OL_2EuXwux5hqJTAu6Ai1A-IzJoX1U61',
    '1zNUpWPzsS_0p535NgfdK0X7-PmHfVD4g',
    '1QE9AONi-VtexAvaCtnZ1drUifCT-F3nN',  // Already shared
    '1Qy3c4cbVLqZk-XmwEteGTNFytpYeh7P_'
  ];
  
  let successCount = 0;
  let errorCount = 0;
  let alreadySharedCount = 0;
  
  Logger.log('Starting to share ' + FOLDER_IDS.length + ' folders with ' + BOT_EMAIL);
  
  for (const folderId of FOLDER_IDS) {
    try {
      const folder = DriveApp.getFolderById(folderId);
      const folderName = folder.getName();
      
      // Check if already shared
      const editors = folder.getEditors();
      const viewers = folder.getViewers();
      let alreadyShared = false;
      
      for (const editor of editors) {
        if (editor.getEmail() === BOT_EMAIL) {
          alreadyShared = true;
          break;
        }
      }
      
      if (!alreadyShared) {
        for (const viewer of viewers) {
          if (viewer.getEmail() === BOT_EMAIL) {
            alreadyShared = true;
            break;
          }
        }
      }
      
      if (alreadyShared) {
        Logger.log('✓ Already shared: ' + folderName + ' (' + folderId + ')');
        alreadySharedCount++;
        continue;
      }
      
      // Share with viewer (read-only) permission
      folder.addViewer(BOT_EMAIL);
      Logger.log('✓ Shared: ' + folderName + ' (' + folderId + ')');
      successCount++;
      
      // Small delay to avoid rate limits
      Utilities.sleep(500);
      
    } catch (error) {
      Logger.log('✗ Error with folder ' + folderId + ': ' + error.toString());
      errorCount++;
    }
  }
  
  Logger.log('\n=== SUMMARY ===');
  Logger.log('Total folders: ' + FOLDER_IDS.length);
  Logger.log('Newly shared: ' + successCount);
  Logger.log('Already shared: ' + alreadySharedCount);
  Logger.log('Errors: ' + errorCount);
  
  return {
    total: FOLDER_IDS.length,
    success: successCount,
    alreadyShared: alreadySharedCount,
    errors: errorCount
  };
}

/**
 * Alternative: Find and share by folder name pattern
 * Use this if folder IDs don't work (e.g., folders were moved)
 */
function findAndShareByPattern() {
  const BOT_EMAIL = 'davidyaneleonora@gmail.com';
  const searchTerms = ['developer', 'застройщик', 'price', 'остатки', 'inventory'];
  
  let sharedCount = 0;
  
  for (const term of searchTerms) {
    const folders = DriveApp.searchFolders('title contains "' + term + '"');
    
    while (folders.hasNext()) {
      const folder = folders.next();
      try {
        folder.addViewer(BOT_EMAIL);
        Logger.log('Shared: ' + folder.getName());
        sharedCount++;
        Utilities.sleep(300);
      } catch (e) {
        Logger.log('Error sharing ' + folder.getName() + ': ' + e);
      }
    }
  }
  
  Logger.log('Total shared: ' + sharedCount);
  return sharedCount;
}
