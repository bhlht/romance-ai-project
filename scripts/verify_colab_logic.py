import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import zipfile
import shutil

# Mocking libraries to avoid heavy imports or missing dependencies during test
sys.modules["torch"] = MagicMock()
sys.modules["datasets"] = MagicMock()
sys.modules["transformers"] = MagicMock()
sys.modules["peft"] = MagicMock()
sys.modules["trl"] = MagicMock()
sys.modules["bitsandbytes"] = MagicMock() 

# Now import the script under test
# We need to add the scripts dir to path provided we are running from root or similar
scripts_path = os.path.join(os.getcwd(), 'scripts')
if scripts_path not in sys.path:
    sys.path.append(scripts_path)

try:
    import train_model
except ImportError:
    # If unrelated failure, raise
    raise

class TestColabLogic(unittest.TestCase):
    def setUp(self):
        self.test_zip = "test_data.zip"
        self.test_extract_dir = "temp_test_extract"
        
        # Create a dummy zip
        with zipfile.ZipFile(self.test_zip, 'w') as zf:
            zf.writestr("test_file.txt", "This is some dummy training data.")

        
        # Configure torch mock to avoid unpacking errors
        torch_mock = sys.modules["torch"]
        torch_mock.cuda.is_available.return_value = True
        torch_mock.cuda.get_device_capability.return_value = (8, 0)

    def tearDown(self):
        if os.path.exists(self.test_zip):
            os.remove(self.test_zip)
        if os.path.exists(self.test_extract_dir):
            shutil.rmtree(self.test_extract_dir)
        # Also clean up what setup_data might have created if we didn't mock paths
        if os.path.exists("/content/temp_data.zip"):
            try:
                os.remove("/content/temp_data.zip")
            except:
                pass
        if os.path.exists("/content/temp_data_extracted"):
            try:
                shutil.rmtree("/content/temp_data_extracted")
            except:
                pass

    def test_setup_data_zip_handling(self):
        """Test that setup_data correctly identifies zips, copies/unzips them."""
        print(f"DEBUG: train_model attributes: {dir(train_model)}")
        
        # Mocking shutil.copy and zipfile.ZipFile in train_model module
        with patch("train_model.shutil.copy") as mock_copy, \
             patch("train_model.zipfile.ZipFile") as mock_zip:
            
            # Setup mock for zipfile context manager
            mock_zip_instance = MagicMock()
            mock_zip.return_value.__enter__.return_value = mock_zip_instance
            
            # Patch os.walk globally since train_model.os.walk might follow 'os' module
            with patch("os.walk") as mock_walk:
                mock_walk.return_value = [
                    ("/content/temp_data_extracted", [], ["data.txt"])
                ]
                
                result_path = train_model.setup_data(self.test_zip)
                
                # Check if copy was called
                mock_copy.assert_called()
                # Check if unzip was called
                mock_zip_instance.extractall.assert_called()
                # Check return path (should be the found file)
                self.assertTrue(result_path.endswith("data.txt"))

    @patch("trl.SFTTrainer")
    @patch("train_model.AutoModelForCausalLM")
    @patch("train_model.AutoTokenizer")
    @patch("train_model.load_dataset")
    def test_train_finally_block(self, mock_load_dataset, mock_tokenizer, mock_model, mock_trainer):
        """Test that save_pretrained is called even if training fails."""
        
        # Setup mocks
        mock_trainer_instance = MagicMock()
        mock_trainer.return_value = mock_trainer_instance
        
        # Make train raise an exception
        mock_trainer_instance.train.side_effect = RuntimeError("Colab Disconnect")
        
        # Run train(), expect it to raise but also call save
        with self.assertRaises(RuntimeError):
            train_model.train("model_name", "data.txt", "output_dir")
            
        # Verify save was called in finally block
        mock_trainer_instance.model.save_pretrained.assert_called_with("output_dir")
        
if __name__ == "__main__":
    unittest.main()
