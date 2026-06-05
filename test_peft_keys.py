from peft import LoraConfig
import inspect
valid_keys = set(inspect.signature(LoraConfig.__init__).parameters.keys())
valid_keys.update(["peft_type", "auto_mapping", "base_model_name_or_path", "revision", "task_type", "inference_mode"])

hf_keys = [
 'alora_invocation_tokens',
 'alpha_pattern',
 'arrow_config',
 'auto_mapping',
 'base_model_name_or_path',
 'bias',
 'corda_config',
 'ensure_weight_tying',
 'eva_config',
 'exclude_modules',
 'fan_in_fan_out',
 'inference_mode',
 'init_lora_weights',
 'layer_replication',
 'layers_pattern',
 'layers_to_transform',
 'loftq_config',
 'lora_alpha',
 'lora_bias',
 'lora_dropout',
 'megatron_config',
 'megatron_core',
 'modules_to_save',
 'peft_type',
 'peft_version',
 'qalora_group_size',
 'r',
 'rank_pattern',
 'revision',
 'target_modules',
 'target_parameters',
 'task_type',
 'trainable_token_indices',
 'use_dora',
 'use_qalora',
 'use_rslora'
]

keys_to_remove = [k for k in hf_keys if k not in valid_keys]
print("DELETED KEYS:", keys_to_remove)
