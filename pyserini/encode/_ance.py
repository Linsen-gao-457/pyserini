#
# Pyserini: Reproducible IR research with sparse and dense representations
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from typing import Optional, List

import torch
from transformers import PreTrainedModel, RobertaConfig, RobertaModel, RobertaTokenizer, requires_backends

from pyserini.encode import DocumentEncoder, QueryEncoder


class AnceEncoder(PreTrainedModel):
    config_class = RobertaConfig
    base_model_prefix = 'ance_encoder'
    load_tf_weights = None

    def __init__(self, config: RobertaConfig):
        requires_backends(self, 'torch')
        super().__init__(config)
        self.config = config
        self.roberta = RobertaModel(config)
        self.embeddingHead = torch.nn.Linear(config.hidden_size, 768)
        self.norm = torch.nn.LayerNorm(768)
        self.init_weights()

    # Copied from transformers.models.bert.modeling_bert.BertPreTrainedModel._init_weights
    def _init_weights(self, module):
        """ Initialize the weights """
        if isinstance(module, (torch.nn.Linear, torch.nn.Embedding)):
            # Slightly different from the TF version which uses truncated_normal for initialization
            # cf https://github.com/pytorch/pytorch/pull/5617
            module.weight.data.normal_(mean=0.0, std=self.config.initializer_range)
        elif isinstance(module, torch.nn.LayerNorm):
            module.bias.data.zero_()
            module.weight.data.fill_(1.0)
        if isinstance(module, torch.nn.Linear) and module.bias is not None:
            module.bias.data.zero_()

    def init_weights(self):
        self.roberta.init_weights()
        self.embeddingHead.apply(self._init_weights)
        self.norm.apply(self._init_weights)

    def forward(self, input_ids: torch.Tensor, attention_mask: Optional[torch.Tensor] = None):
        input_shape = input_ids.size()
        device = input_ids.device
        if attention_mask is None:
            attention_mask = (
                torch.ones(input_shape, device=device)
                if input_ids is None
                else (input_ids != self.roberta.config.pad_token_id)
            )
        outputs = self.roberta(input_ids=input_ids, attention_mask=attention_mask)
        sequence_output = outputs.last_hidden_state
        pooled_output = sequence_output[:, 0, :]
        pooled_output = self.norm(self.embeddingHead(pooled_output))
        return pooled_output


class AnceDocumentEncoder(DocumentEncoder):
    def __init__(self, model_name, tokenizer_name=None, device='cuda:0'):
        self.device = device
        self.model = AnceEncoder.from_pretrained(model_name)
        self.model.to(self.device)
        self.tokenizer = RobertaTokenizer.from_pretrained(tokenizer_name or model_name,
                                                          clean_up_tokenization_spaces=True)

    def encode(self, texts, titles=None,  max_length=256, **kwargs):
        if titles is not None:
            texts = [f'{title} {text}' for title, text in zip(titles, texts)]
        inputs = self.tokenizer(
            texts,
            max_length=max_length,
            padding='longest',
            truncation=True,
            add_special_tokens=True,
            return_tensors='pt'
        )
        inputs.to(self.device)
        return self.model(inputs["input_ids"]).detach().cpu().numpy()


class AnceQueryEncoder(QueryEncoder):
    def __init__(self, encoder_dir: str = None, tokenizer_name: str = None,
                 encoded_query_dir: str = None, device: str = 'cpu', **kwargs):
        super().__init__(encoded_query_dir)
        if encoder_dir:
            self.device = device
            self.model = AnceEncoder.from_pretrained(encoder_dir)
            self.model.to(self.device)
            self.tokenizer = RobertaTokenizer.from_pretrained(tokenizer_name or encoder_dir,
                                                              clean_up_tokenization_spaces=True)
            self.has_model = True
            self.tokenizer.do_lower_case = True
        if (not self.has_model) and (not self.has_encoded_query):
            raise Exception('Neither query encoder model nor encoded queries provided. Please provide at least one')

    def encode(self, query: str):
        if self.has_model:
            inputs = self.tokenizer(
                [query],
                max_length=64,
                padding='longest',
                truncation=True,
                add_special_tokens=True,
                return_tensors='pt'
            )
            inputs.to(self.device)
            embeddings = self.model(inputs["input_ids"]).detach().cpu().numpy()
            return embeddings.flatten()
        else:
            return super().encode(query)

    def prf_encode(self, query: str):
        if self.has_model:
            inputs = self.tokenizer(
                [query],
                max_length=512,
                padding='longest',
                truncation=True,
                add_special_tokens=False,
                return_tensors='pt'
            )
            inputs.to(self.device)
            embeddings = self.model(inputs["input_ids"]).detach().cpu().numpy()
            return embeddings.flatten()
        else:
            return super().encode(query)

    def prf_batch_encode(self, query: List[str]):
        inputs = self.tokenizer(
            query,
            max_length=512,
            padding='longest',
            truncation=True,
            add_special_tokens=False,
            return_tensors='pt'
        )
        inputs.to(self.device)
        embeddings = self.model(inputs["input_ids"]).detach().cpu().numpy()
        return embeddings
