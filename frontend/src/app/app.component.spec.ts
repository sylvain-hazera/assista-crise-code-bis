import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { fournisseursDeTest } from './testing/test-providers';

describe('AppComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [AppComponent],
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it(`should have the 'assista-crise-front' title`, () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    expect(app.title).toEqual('assista-crise-front');
  });

  // Le test « should render title » laissé par `ng new` cherchait un « Hello,
  // assista-crise-front » dans un <h1> : ce gabarit d'échafaudage a été remplacé le premier
  // jour du projet. Il n'était jamais rouge parce que la suite ne démarrait pas, et il
  // n'affirmait rien de réel — supprimé plutôt que rafistolé.
});
