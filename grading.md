- [ ] ~~comments~~
- [x] github
- [x] license
- [x] demo

Q: User agreement/TOS

## TODO
- [ ] ~~embedding async~~
- [x] delete embedding on oppinion delete
- [x] Check search caching, 5-point star rendering
- [x] Query should include sentiment too
- [ ] ~~Move js, cssgi out of html~~
- [x] Implement clustering, extract topic foreach cluster ~~using fasttopic~~ -> set umap parameters based on clusters automatically
- [x] where to get ~~~~smartvote data~~ from? => generate statements & arguments using python script
- [x] Make clustering use multiple cores
- [ ] ~~automatically recluster, adjust cluster size~~
- [x] normalize topic label capitalization, eliminate duplicates, improve stop words
- [x] add uv run way to readme
- [x] dynamic topics explore

- [ ] ~~Add sentiment input value [-1,1] (how much do I agree with statement), multiply by sentiment analysis on statement~~
- [ ] ~~Maybe (?) add negations for stop words like "hate"? TODO~~
- [ ] ~~political (instead of) map for location selection~~
- [x] add user name
- [x] Make up/fetch locations & time for the oppinions
- [x] Actually show n clusters if n topics are selected with slider in search view
- [x] fix dark background for embedding map

- [ ] presentation ready?
- [ ] update legal part in the end, TOS

- [ ] clusters in "Sentiment overview" made up -> missleading




- [ ] remove "show more" button, when all are shown for oppinions list.
  
  # Fine for now
- [ ] Filter my location, user, ~~time~~
- [ ] Move docker file to alpine linux, current setup looks like a mess (claude code -_-)
- [ ] What is "contribution" table used for?
- [ ] remove private imputs
- [ ] move js in opinions/templates/opinions/_cluster_results.html to external js file
- [ ] Allow searching for all/without statement