// Use browser-native word segmentation so Chinese titles and body text are searchable.
if (i === Object.keys(docs)[0]) {
  var segmenter = new Intl.Segmenter('zh-CN', { granularity: 'word' });
  lunr.tokenizer = function (value, metadata) {
    var text = Array.isArray(value) ? value.join(' ') : String(value || '');
    return Array.from(segmenter.segment(text.toLowerCase()))
      .filter(function (part) { return part.isWordLike; })
      .map(function (part) {
        return new lunr.Token(part.segment, Object.assign({}, metadata, {
          position: [part.index, part.segment.length]
        }));
      });
  };
  this.tokenizer = lunr.tokenizer;
  this.pipeline.reset();
  this.searchPipeline.reset();
}
